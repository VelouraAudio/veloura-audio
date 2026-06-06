"""Small PCM helpers with an audioop-compatible fallback.

Veloura mixes signed 16-bit little-endian PCM. Python's ``audioop`` is fast
when present, but it is deprecated and unavailable on newer Python versions, so
the package keeps a pure-Python path for portability.
"""

from __future__ import annotations

import math

try:
    import audioop as _audioop
except ImportError:  # pragma: no cover - exercised on Python builds without audioop
    _audioop = None


MIN_SAMPLE_16 = -32768
MAX_SAMPLE_16 = 32767


def _require_s16le(sample_width: int):
    if sample_width != 2:
        raise ValueError("Veloura PCM fallback supports signed 16-bit samples only.")


def _clip_s16(value: float) -> int:
    return max(MIN_SAMPLE_16, min(MAX_SAMPLE_16, int(round(value))))


def _read_s16le(frame: bytes, offset: int) -> int:
    return int.from_bytes(frame[offset : offset + 2], "little", signed=True)


def _write_s16le(buffer: bytearray, offset: int, value: int):
    buffer[offset : offset + 2] = int(value).to_bytes(2, "little", signed=True)


def pcm_mul(frame: bytes, sample_width: int, gain: float) -> bytes:
    if _audioop is not None:
        return _audioop.mul(frame, sample_width, gain)

    _require_s16le(sample_width)
    if not frame:
        return b""
    output = bytearray(frame)
    frame_end = len(frame) - (len(frame) % sample_width)
    for offset in range(0, frame_end, sample_width):
        _write_s16le(output, offset, _clip_s16(_read_s16le(frame, offset) * gain))
    return bytes(output)


def pcm_add(left: bytes, right: bytes, sample_width: int) -> bytes:
    if _audioop is not None:
        return _audioop.add(left, right, sample_width)

    _require_s16le(sample_width)
    if len(left) != len(right):
        raise ValueError("PCM buffers must have the same length.")
    output = bytearray(left)
    frame_end = len(left) - (len(left) % sample_width)
    for offset in range(0, frame_end, sample_width):
        sample = _read_s16le(left, offset) + _read_s16le(right, offset)
        _write_s16le(output, offset, _clip_s16(sample))
    return bytes(output)


def pcm_rms(frame: bytes, sample_width: int) -> int:
    if _audioop is not None:
        return _audioop.rms(frame, sample_width)

    _require_s16le(sample_width)
    if not frame:
        return 0
    frame_end = len(frame) - (len(frame) % sample_width)
    count = frame_end // sample_width
    if count <= 0:
        return 0
    total = 0
    for offset in range(0, frame_end, sample_width):
        sample = _read_s16le(frame, offset)
        total += sample * sample
    return int(math.sqrt(total / count))
