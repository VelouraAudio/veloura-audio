"""Small Listening Model transition planning.

The public Veloura SLM is deterministic and local-only. It does not call a
hosted model or collect listener data; it scores the pair in front of it and
chooses a practical crossfade duration that AutoMix can apply.
"""

from __future__ import annotations

from dataclasses import dataclass

from .beat import BeatProfile, MIN_BEAT_CONFIDENCE, compatible_bpm_delta
from .models import AudioTrack
from .transition import (
    SmartTransitionConfig,
    clamp,
    looks_like_non_studio_track,
    normalize_transition_config,
    planned_crossfade_seconds,
)

SLM_TRANSITION_VERSION = 1


@dataclass(frozen=True)
class SLMTransitionPlan:
    crossfade_seconds: float
    confidence: float
    reason: str
    current_duration: float
    next_duration: float
    bpm_delta: float | None = None
    safety_capped: bool = False
    version: int = SLM_TRANSITION_VERSION


def plan_slm_transition(
    current: AudioTrack,
    next_track: AudioTrack,
    config: SmartTransitionConfig,
    *,
    current_profile: BeatProfile | None = None,
    next_profile: BeatProfile | None = None,
) -> SLMTransitionPlan:
    """Choose an automatic pair-specific crossfade duration.

    This is Veloura's first public Small Listening Model: a conservative local
    scorer that uses duration, title safety checks, and optional beat profiles.
    It is intentionally deterministic so app developers can trust and debug it.
    """

    config = normalize_transition_config(config)
    current_duration = track_duration(current)
    next_duration = track_duration(next_track)
    base = planned_crossfade_seconds(current, config)
    upper = pair_crossfade_ceiling(current_duration, next_duration, config)
    target = base
    confidence = 0.2 if current_duration or next_duration else 0.05
    reason = "duration-fallback"
    bpm_delta: float | None = None

    if current_profile and next_profile:
        profile_confidence = min(
            float(current_profile.confidence or 0.0),
            float(next_profile.confidence or 0.0),
        )
        bpm_delta = compatible_bpm_delta(current_profile.bpm, next_profile.bpm)
        confidence = clamp(profile_confidence, 0.0, 1.0)

        if profile_confidence < MIN_BEAT_CONFIDENCE:
            target = min(base, 4.0)
            reason = "low-beat-confidence"
        elif bpm_delta <= 4.0:
            target = max(base, 10.0)
            confidence = clamp(0.55 + profile_confidence * 0.4, 0.0, 0.95)
            reason = "beat-and-energy-match"
        elif bpm_delta <= 10.0:
            target = max(base, 7.0)
            confidence = clamp(0.45 + profile_confidence * 0.35, 0.0, 0.85)
            reason = "near-tempo-match"
        else:
            target = min(base, 5.0)
            confidence = clamp(0.3 + profile_confidence * 0.25, 0.0, 0.65)
            reason = "tempo-mismatch-short-blend"
    else:
        target = min(base, 4.0)

    target, reason, safety_capped = apply_safety_caps(
        target,
        reason,
        current,
        next_track,
        current_duration,
        next_duration,
        config,
    )
    crossfade = clamp(target, 0.0, upper)

    return SLMTransitionPlan(
        crossfade_seconds=round(crossfade, 2),
        confidence=round(confidence, 3),
        reason=f"slm-{reason}",
        current_duration=round(current_duration, 3),
        next_duration=round(next_duration, 3),
        bpm_delta=round(bpm_delta, 2) if bpm_delta is not None else None,
        safety_capped=safety_capped,
    )


def track_duration(track: AudioTrack) -> float:
    return max(
        0.0,
        float(track.effective_playable_duration or track.playable_duration or track.duration or 0.0),
    )


def pair_crossfade_ceiling(
    current_duration: float,
    next_duration: float,
    config: SmartTransitionConfig,
) -> float:
    ceiling = float(config.max_crossfade_seconds)
    if current_duration > 0:
        ceiling = min(ceiling, current_duration / 3.0)
    if next_duration > 0:
        ceiling = min(ceiling, next_duration / 2.0)
    return max(0.0, ceiling)


def apply_safety_caps(
    target: float,
    reason: str,
    current: AudioTrack,
    next_track: AudioTrack,
    current_duration: float,
    next_duration: float,
    config: SmartTransitionConfig,
) -> tuple[float, str, bool]:
    if looks_like_non_studio_track(current.title) or looks_like_non_studio_track(next_track.title):
        return min(target, 3.0), "non-studio-short-blend", True

    known_durations = [duration for duration in (current_duration, next_duration) if duration > 0]
    shortest_known = min(known_durations) if known_durations else 0.0
    if shortest_known:
        if shortest_known < 45.0:
            return min(target, 2.0), "short-track", True
        if shortest_known < 90.0:
            return min(target, 4.0), "medium-short-track", True
        if shortest_known < 150.0:
            return min(target, 6.0), "medium-track", True

    if current.trim_end >= 2.0:
        return (
            min(target, max(config.min_crossfade_seconds, config.base_crossfade_seconds * 0.65)),
            "outro-trim-short-blend",
            True,
        )

    return target, reason, False
