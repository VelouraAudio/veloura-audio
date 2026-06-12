"""Lossless-quality transition rendering for file outputs."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .ffmpeg_binary import require_ffmpeg
from .models import AudioTrack

CURVE_RE = re.compile(r"^[a-z0-9_+-]+$")


@dataclass(frozen=True)
class LosslessTransitionConfig:
    """Settings for rendering a transition into a lossless output file.

    This renderer is for local files, music apps, demos, and release-prep
    workflows. It does not make Discord voice output lossless.
    """

    crossfade_seconds: float = 8.0
    sample_rate: int = 48_000
    channels: int = 2
    curve: str = "qsin"
    limiter: bool = True
    overwrite: bool = True


def coerce_track(source: AudioTrack | str | Path) -> AudioTrack:
    if isinstance(source, AudioTrack):
        return source
    path = Path(source)
    return AudioTrack.from_source(str(source), title=path.stem or str(source))


def channel_layout(channels: int) -> str:
    if channels == 1:
        return "mono"
    if channels == 2:
        return "stereo"
    raise ValueError("lossless transition rendering supports 1 or 2 channels.")


def normalize_lossless_config(config: LosslessTransitionConfig | None = None) -> LosslessTransitionConfig:
    config = config or LosslessTransitionConfig()
    channels = int(config.channels)
    channel_layout(channels)
    curve = (config.curve or "qsin").strip().lower()
    if not CURVE_RE.match(curve):
        raise ValueError("invalid FFmpeg fade curve name.")
    return LosslessTransitionConfig(
        crossfade_seconds=max(0.05, min(120.0, float(config.crossfade_seconds))),
        sample_rate=int(max(8_000, min(384_000, int(config.sample_rate)))),
        channels=channels,
        curve=curve,
        limiter=bool(config.limiter),
        overwrite=bool(config.overwrite),
    )


def codec_args_for_output(output: str | Path) -> list[str]:
    suffix = Path(output).suffix.lower()
    if suffix == ".flac":
        return ["-c:a", "flac", "-compression_level", "8"]
    if suffix == ".wav":
        return ["-c:a", "pcm_f32le"]
    if suffix in {".m4a", ".alac"}:
        return ["-c:a", "alac"]
    if suffix in {".aif", ".aiff"}:
        return ["-c:a", "pcm_s24be"]
    raise ValueError("lossless output must end with .flac, .wav, .m4a, .alac, .aif, or .aiff.")


def trim_filter(track: AudioTrack) -> str:
    parts: list[str] = []
    if track.trim_start > 0:
        parts.append(f"start={track.trim_start:.6f}")
    if track.duration and track.trim_end > 0:
        end_at = max(0.0, float(track.duration) - float(track.trim_end))
        if end_at > float(track.trim_start):
            parts.append(f"end={end_at:.6f}")
    if not parts:
        return ""
    return f"atrim={':'.join(parts)},"


def source_filter(index: int, track: AudioTrack, config: LosslessTransitionConfig) -> str:
    layout = channel_layout(config.channels)
    return (
        f"[{index}:a]"
        f"{trim_filter(track)}"
        "asetpts=PTS-STARTPTS,"
        f"aresample={config.sample_rate},"
        f"aformat=sample_fmts=fltp:channel_layouts={layout}"
        f"[a{index}]"
    )


def build_lossless_transition_command(
    ffmpeg: str,
    current: AudioTrack | str | Path,
    next_track: AudioTrack | str | Path,
    output: str | Path,
    config: LosslessTransitionConfig | None = None,
) -> list[str]:
    config = normalize_lossless_config(config)
    current_track = coerce_track(current)
    following_track = coerce_track(next_track)
    output_path = Path(output)

    filters = [
        source_filter(0, current_track, config),
        source_filter(1, following_track, config),
    ]
    transition = (
        f"[a0][a1]acrossfade=d={config.crossfade_seconds:.6f}:"
        f"c1={config.curve}:c2={config.curve}"
    )
    if config.limiter:
        transition += ",alimiter=limit=0.98"
    transition += "[out]"
    filters.append(transition)

    command = [
        ffmpeg,
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "error",
        "-y" if config.overwrite else "-n",
        "-i",
        current_track.stream_url,
        "-i",
        following_track.stream_url,
        "-filter_complex",
        ";".join(filters),
        "-map",
        "[out]",
        "-vn",
    ]
    command.extend(codec_args_for_output(output_path))
    command.append(str(output_path))
    return command


def render_lossless_transition(
    current: AudioTrack | str | Path,
    next_track: AudioTrack | str | Path,
    output: str | Path,
    config: LosslessTransitionConfig | None = None,
    *,
    timeout: float | None = None,
) -> Path:
    """Render a lossless-quality transition file and return the output path."""

    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = build_lossless_transition_command(
        require_ffmpeg(),
        current,
        next_track,
        output_path,
        config,
    )
    result = subprocess.run(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        error = result.stderr.decode("utf-8", "ignore").strip()
        raise RuntimeError(error or "ffmpeg failed to render the lossless transition.")
    return output_path
