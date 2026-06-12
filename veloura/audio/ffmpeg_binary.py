"""FFmpeg executable discovery helpers."""

from __future__ import annotations

import os
import shutil
from pathlib import Path


def _resolve_executable(value: str | None) -> str | None:
    if not value:
        return None

    expanded = os.path.expanduser(value)
    has_path_separator = os.path.sep in expanded or (os.path.altsep and os.path.altsep in expanded)
    if has_path_separator or Path(expanded).is_absolute():
        path = Path(expanded)
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
        return None

    return shutil.which(expanded)


def resolve_ffmpeg() -> str | None:
    """Return a usable ffmpeg executable path.

    Veloura prefers an explicit environment override, then a system ffmpeg, then
    the bundled executable exposed by imageio-ffmpeg.
    """

    configured = os.getenv("VELOURA_FFMPEG") or os.getenv("IMAGEIO_FFMPEG_EXE")
    if configured:
        return _resolve_executable(configured)

    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg

    try:
        from imageio_ffmpeg import get_ffmpeg_exe
    except Exception:
        return None

    try:
        return get_ffmpeg_exe()
    except Exception:
        return None


def require_ffmpeg() -> str:
    ffmpeg = resolve_ffmpeg()
    if ffmpeg:
        return ffmpeg
    raise RuntimeError(
        "ffmpeg was not found. Install veloura-audio normally to include the "
        "bundled imageio-ffmpeg provider, or set VELOURA_FFMPEG to an ffmpeg executable."
    )


def resolve_ffprobe() -> str | None:
    configured = os.getenv("VELOURA_FFPROBE")
    if configured:
        return _resolve_executable(configured)
    return shutil.which("ffprobe")


def resolve_ffplay() -> str | None:
    configured = os.getenv("VELOURA_FFPLAY")
    if configured:
        return _resolve_executable(configured)
    return shutil.which("ffplay")
