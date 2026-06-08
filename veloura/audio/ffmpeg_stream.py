"""FFmpeg-backed PCM stream reader."""

import os
import select
import subprocess
from urllib.parse import urlparse

from .constants import CHANNELS, FRAME_BYTES, FRAME_RATE
from .ffmpeg_binary import require_ffmpeg
from .models import MixerTrack

READ_TIMEOUT_SECONDS = 0.25
MAX_EMPTY_READS = 20


def atempo_filter_chain(tempo: float) -> str:
    try:
        ratio = float(tempo or 1.0)
    except (TypeError, ValueError):
        return ""
    if ratio <= 0:
        return ""
    ratio = max(0.5, min(2.0, ratio))
    if abs(ratio - 1.0) < 0.005:
        return ""
    return f"atempo={ratio:.6g}"


def should_use_reconnect(source: str) -> bool:
    scheme = urlparse(source or "").scheme.lower()
    return scheme in {"http", "https"}


def build_ffmpeg_pcm_command(ffmpeg: str, track: MixerTrack) -> list[str]:
    command = [
        ffmpeg,
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "error",
    ]
    if should_use_reconnect(track.stream_url):
        command.extend(
            [
                "-reconnect",
                "1",
                "-reconnect_streamed",
                "1",
                "-reconnect_delay_max",
                "5",
            ]
        )
    if track.trim_start > 0:
        command.extend(["-ss", f"{track.trim_start:.3f}"])

    command.extend(
        [
            "-i",
            track.stream_url,
            "-vn",
            "-threads",
            "1",
        ]
    )

    if track.playable_duration > 0 and (track.trim_start > 0 or track.trim_end > 0):
        command.extend(["-t", f"{track.playable_duration:.3f}"])

    tempo_filter = atempo_filter_chain(track.tempo_ratio)
    if tempo_filter:
        command.extend(["-af", tempo_filter])

    command.extend(
        [
            "-f",
            "s16le",
            "-ar",
            str(FRAME_RATE),
            "-ac",
            str(CHANNELS),
            "pipe:1",
        ]
    )
    return command


class FFmpegPCMStream:
    def __init__(self, track: MixerTrack):
        command = build_ffmpeg_pcm_command(require_ffmpeg(), track)
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=FRAME_BYTES * 8,
        )
        self.empty_reads = 0

    def read_frame(self) -> bytes | None:
        if not self.process.stdout:
            return None
        if self.process.poll() is not None:
            return None

        fileno = self.process.stdout.fileno()
        ready, _, _ = select.select([fileno], [], [], READ_TIMEOUT_SECONDS)
        if not ready:
            self.empty_reads += 1
            if self.empty_reads >= MAX_EMPTY_READS:
                return None
            return b"\x00" * FRAME_BYTES

        data = os.read(fileno, FRAME_BYTES)
        if not data:
            return None
        self.empty_reads = 0
        if len(data) < FRAME_BYTES:
            data += b"\x00" * (FRAME_BYTES - len(data))
        return data

    def close(self):
        try:
            if self.process.stdout:
                self.process.stdout.close()
        except Exception:
            pass
        if self.process.poll() is None:
            try:
                self.process.terminate()
                self.process.wait(timeout=1.0)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
