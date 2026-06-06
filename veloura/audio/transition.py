"""Smart transition planning for smooth music playback."""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass, replace

from .models import MixerTrack

SILENCE_START_RE = re.compile(r"silence_start:\s*([0-9.]+)")
SILENCE_END_RE = re.compile(r"silence_end:\s*([0-9.]+)")
MEAN_VOLUME_RE = re.compile(r"mean_volume:\s*(-?[0-9.]+)\s*dB")
ANALYSIS_VERSION = 1


@dataclass(frozen=True)
class SmartTransitionConfig:
    enabled: bool = True
    base_crossfade_seconds: float = 8.0
    min_crossfade_seconds: float = 2.0
    max_crossfade_seconds: float = 15.0
    analyze_silence: bool = True
    analyze_trailing_silence: bool = False
    silence_threshold_db: float = -45.0
    silence_duration_seconds: float = 0.35
    analysis_window_seconds: float = 18.0
    analysis_timeout_seconds: float = 3.5
    max_intro_trim_seconds: float = 5.0
    max_outro_trim_seconds: float = 8.0
    normalize_loudness: bool = True
    loudness_target_db: float = -18.0
    loudness_min_gain: float = 0.65
    loudness_max_gain: float = 1.35
    loudness_analysis_seconds: float = 24.0


@dataclass(frozen=True)
class SilenceProfile:
    leading_seconds: float = 0.0
    trailing_seconds: float = 0.0
    analyzed: bool = False


@dataclass(frozen=True)
class LoudnessProfile:
    mean_volume_db: float | None = None
    gain: float = 1.0
    analyzed: bool = False


def clamp(value: float, minimum: float, maximum: float) -> float:
    if maximum < minimum:
        minimum, maximum = maximum, minimum
    return max(minimum, min(maximum, value))


def normalize_transition_config(config: SmartTransitionConfig) -> SmartTransitionConfig:
    max_crossfade = clamp(float(config.max_crossfade_seconds), 0.0, 60.0)
    min_crossfade = clamp(float(config.min_crossfade_seconds), 0.0, max_crossfade)
    loudness_min_gain = clamp(float(config.loudness_min_gain), 0.0, 2.0)
    loudness_max_gain = clamp(float(config.loudness_max_gain), loudness_min_gain, 2.0)
    return replace(
        config,
        base_crossfade_seconds=clamp(float(config.base_crossfade_seconds), 0.0, max_crossfade),
        min_crossfade_seconds=min_crossfade,
        max_crossfade_seconds=max_crossfade,
        silence_threshold_db=clamp(float(config.silence_threshold_db), -90.0, -10.0),
        silence_duration_seconds=clamp(float(config.silence_duration_seconds), 0.05, 5.0),
        analysis_window_seconds=clamp(float(config.analysis_window_seconds), 1.0, 120.0),
        analysis_timeout_seconds=clamp(float(config.analysis_timeout_seconds), 0.5, 60.0),
        max_intro_trim_seconds=clamp(float(config.max_intro_trim_seconds), 0.0, 30.0),
        max_outro_trim_seconds=clamp(float(config.max_outro_trim_seconds), 0.0, 30.0),
        loudness_target_db=clamp(float(config.loudness_target_db), -36.0, -6.0),
        loudness_min_gain=loudness_min_gain,
        loudness_max_gain=loudness_max_gain,
        loudness_analysis_seconds=clamp(float(config.loudness_analysis_seconds), 1.0, 120.0),
    )


def looks_like_non_studio_track(title: str) -> bool:
    lowered = title.lower()
    markers = (
        "interview",
        "podcast",
        "speech",
        "dialogue",
        "skit",
        "live",
        "concert",
        "acoustic session",
    )
    return any(marker in lowered for marker in markers)


def planned_crossfade_seconds(track: MixerTrack, config: SmartTransitionConfig) -> float:
    config = normalize_transition_config(config)
    if not config.enabled:
        return 0.0

    duration = track.playable_duration or float(track.duration or 0)
    if duration <= 0:
        return clamp(config.base_crossfade_seconds, 0.0, config.max_crossfade_seconds)

    base = clamp(
        config.base_crossfade_seconds,
        config.min_crossfade_seconds,
        config.max_crossfade_seconds,
    )

    if looks_like_non_studio_track(track.title):
        base = min(base, 3.0)
    elif duration < 45:
        base = min(base, 2.0)
    elif duration < 90:
        base = min(base, 4.0)
    elif duration < 150:
        base = min(base, 6.0)

    if track.trim_end >= 2.0:
        base = min(base, max(config.min_crossfade_seconds, config.base_crossfade_seconds * 0.65))

    return clamp(base, 0.0, min(config.max_crossfade_seconds, max(1.0, duration / 3)))


def analyze_silence(track: MixerTrack, config: SmartTransitionConfig) -> SilenceProfile:
    config = normalize_transition_config(config)
    if not config.enabled or not config.analyze_silence:
        return SilenceProfile()
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return SilenceProfile()

    leading = analyze_leading_silence(ffmpeg, track, config)
    trailing = 0.0
    if config.analyze_trailing_silence and track.duration:
        trailing = analyze_trailing_silence(ffmpeg, track, config)

    return SilenceProfile(
        leading_seconds=leading,
        trailing_seconds=trailing,
        analyzed=bool(leading or trailing),
    )


def analyze_loudness(track: MixerTrack, config: SmartTransitionConfig) -> LoudnessProfile:
    config = normalize_transition_config(config)
    if not config.enabled or not config.normalize_loudness:
        return LoudnessProfile()
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return LoudnessProfile()

    output = run_volumedetect(
        ffmpeg,
        track.stream_url,
        config,
        start_at=track.trim_start if track.trim_start > 0 else None,
        duration=min(config.loudness_analysis_seconds, track.playable_duration or config.loudness_analysis_seconds),
    )
    match = MEAN_VOLUME_RE.search(output or "")
    if not match:
        return LoudnessProfile()

    mean_volume_db = float(match.group(1))
    gain_db = config.loudness_target_db - mean_volume_db
    gain = 10 ** (gain_db / 20)
    return LoudnessProfile(
        mean_volume_db=mean_volume_db,
        gain=clamp(gain, config.loudness_min_gain, config.loudness_max_gain),
        analyzed=True,
    )


def analyze_leading_silence(ffmpeg: str, track: MixerTrack, config: SmartTransitionConfig) -> float:
    output = run_silencedetect(
        ffmpeg,
        track.stream_url,
        config,
        start_at=None,
        duration=config.analysis_window_seconds,
    )
    if not output:
        return 0.0

    starts = [float(value) for value in SILENCE_START_RE.findall(output)]
    ends = [float(value) for value in SILENCE_END_RE.findall(output)]
    if not starts or starts[0] > 0.15 or not ends:
        return 0.0
    return clamp(ends[0], 0.0, config.max_intro_trim_seconds)


def analyze_trailing_silence(ffmpeg: str, track: MixerTrack, config: SmartTransitionConfig) -> float:
    duration = float(track.duration or 0)
    if duration <= 0:
        return 0.0

    window = min(config.analysis_window_seconds, duration)
    segment_start = max(0.0, duration - window)
    output = run_silencedetect(
        ffmpeg,
        track.stream_url,
        config,
        start_at=segment_start,
        duration=window,
    )
    if not output:
        return 0.0

    starts = [
        normalize_segment_time(float(value), segment_start, window)
        for value in SILENCE_START_RE.findall(output)
    ]
    ends = [
        normalize_segment_time(float(value), segment_start, window)
        for value in SILENCE_END_RE.findall(output)
    ]
    if not starts:
        return 0.0

    last_start = starts[-1]
    last_end = ends[-1] if ends else window
    if window - last_end > 0.3:
        return 0.0
    return clamp(window - last_start, 0.0, config.max_outro_trim_seconds)


def normalize_segment_time(value: float, segment_start: float, window: float) -> float:
    if value > window + 1.0 and value >= segment_start:
        return max(0.0, value - segment_start)
    return value


def run_silencedetect(
    ffmpeg: str,
    source: str,
    config: SmartTransitionConfig,
    *,
    start_at: float | None,
    duration: float,
) -> str:
    command = [
        ffmpeg,
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "info",
    ]
    if start_at is not None and start_at > 0:
        command.extend(["-ss", f"{start_at:.3f}"])
    command.extend(
        [
            "-t",
            f"{max(1.0, duration):.3f}",
            "-i",
            source,
            "-vn",
            "-af",
            f"silencedetect=n={config.silence_threshold_db:g}dB:d={config.silence_duration_seconds:g}",
            "-f",
            "null",
            "-",
        ]
    )

    try:
        result = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=max(0.5, config.analysis_timeout_seconds),
            check=False,
        )
    except Exception:
        return ""
    return result.stderr or ""


def run_volumedetect(
    ffmpeg: str,
    source: str,
    config: SmartTransitionConfig,
    *,
    start_at: float | None,
    duration: float,
) -> str:
    command = [
        ffmpeg,
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "info",
    ]
    if start_at is not None and start_at > 0:
        command.extend(["-ss", f"{start_at:.3f}"])
    command.extend(
        [
            "-t",
            f"{max(1.0, duration):.3f}",
            "-i",
            source,
            "-vn",
            "-af",
            "volumedetect",
            "-f",
            "null",
            "-",
        ]
    )

    try:
        result = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=max(0.5, config.analysis_timeout_seconds),
            check=False,
        )
    except Exception:
        return ""
    return result.stderr or ""


def apply_cached_analysis(track: MixerTrack, cached_analysis: dict) -> bool:
    if cached_analysis.get("version") != ANALYSIS_VERSION:
        return False
    track.trim_start = float(cached_analysis.get("trim_start", 0.0) or 0.0)
    track.trim_end = float(cached_analysis.get("trim_end", 0.0) or 0.0)
    track.gain = float(cached_analysis.get("gain", 1.0) or 1.0)
    track.analysis = dict(cached_analysis)
    track.analysis["cached"] = True
    return True


def build_analysis_payload(track: MixerTrack, silence: SilenceProfile, loudness: LoudnessProfile) -> dict:
    return {
        "version": ANALYSIS_VERSION,
        "trim_start": round(float(track.trim_start or 0.0), 3),
        "trim_end": round(float(track.trim_end or 0.0), 3),
        "gain": round(float(track.gain or 1.0), 4),
        "mean_volume_db": loudness.mean_volume_db,
        "silence_analyzed": silence.analyzed,
        "loudness_analyzed": loudness.analyzed,
    }


def prepare_smart_transition(
    track: MixerTrack,
    config: SmartTransitionConfig | None,
    cached_analysis: dict | None = None,
) -> MixerTrack:
    if not config or not config.enabled:
        track.crossfade_seconds = 0.0
        return track
    config = normalize_transition_config(config)

    if cached_analysis and apply_cached_analysis(track, cached_analysis):
        track.crossfade_seconds = planned_crossfade_seconds(track, config)
        return track

    profile = analyze_silence(track, config)
    track.trim_start = profile.leading_seconds
    track.trim_end = profile.trailing_seconds
    loudness = analyze_loudness(track, config)
    track.gain = loudness.gain
    track.crossfade_seconds = planned_crossfade_seconds(track, config)
    track.analysis = build_analysis_payload(track, profile, loudness)
    track.trim_start = float(track.analysis["trim_start"])
    track.trim_end = float(track.analysis["trim_end"])
    track.gain = float(track.analysis["gain"])
    return track
