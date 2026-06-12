"""FFmpeg-backed PCM stream reader."""

import queue
import subprocess
import threading
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
        self.track = track
        self.command = command
        self.closed = threading.Event()
        self.frames: queue.Queue[bytes | None] = queue.Queue(maxsize=16)
        self.stderr_chunks: list[bytes] = []
        self.stderr_lock = threading.Lock()
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=FRAME_BYTES * 8,
        )
        self.empty_reads = 0
        self.stdout_thread = threading.Thread(target=self._read_stdout, name="veloura-ffmpeg-stdout", daemon=True)
        self.stderr_thread = threading.Thread(target=self._read_stderr, name="veloura-ffmpeg-stderr", daemon=True)
        self.stdout_thread.start()
        self.stderr_thread.start()

    def _put_frame(self, frame: bytes | None) -> None:
        while not self.closed.is_set():
            try:
                self.frames.put(frame, timeout=0.1)
                return
            except queue.Full:
                continue

    def _read_stdout(self) -> None:
        try:
            if not self.process.stdout:
                return
            while not self.closed.is_set():
                data = self.process.stdout.read(FRAME_BYTES)
                if not data:
                    return
                if len(data) < FRAME_BYTES:
                    data += b"\x00" * (FRAME_BYTES - len(data))
                self._put_frame(data)
        except Exception:
            return
        finally:
            self._put_frame(None)

    def _read_stderr(self) -> None:
        try:
            if not self.process.stderr:
                return
            while not self.closed.is_set():
                chunk = self.process.stderr.read(1024)
                if not chunk:
                    return
                with self.stderr_lock:
                    self.stderr_chunks.append(chunk)
                    if len(self.stderr_chunks) > 24:
                        self.stderr_chunks = self.stderr_chunks[-24:]
        except Exception:
            return

    def _stderr_text(self) -> str:
        with self.stderr_lock:
            payload = b"".join(self.stderr_chunks)
        return payload.decode("utf-8", "ignore").strip()

    def _raise_if_failed(self) -> None:
        return_code = self.process.poll()
        if return_code is None:
            return
        if return_code == 0:
            return
        message = self._stderr_text()
        last_line = message.splitlines()[-1] if message else "ffmpeg exited without decoded audio."
        raise RuntimeError(last_line)

    def read_frame(self) -> bytes | None:
        try:
            frame = self.frames.get(timeout=READ_TIMEOUT_SECONDS)
        except queue.Empty:
            self.empty_reads += 1
            if self.empty_reads >= MAX_EMPTY_READS:
                self._raise_if_failed()
                return None
            self._raise_if_failed()
            return b"\x00" * FRAME_BYTES

        if frame is None:
            self._raise_if_failed()
            return None

        self.empty_reads = 0
        return frame

    def close(self):
        self.closed.set()
        try:
            if self.process.stdout:
                self.process.stdout.close()
        except Exception:
            pass
        try:
            if self.process.stderr:
                self.process.stderr.close()
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
