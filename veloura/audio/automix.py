"""Pair-aware transition planning for AutoMix-style playback."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from .beat import (
    BeatProfile,
    BeatTransitionPlan,
    analyze_best_source_window,
    is_actionable_beat_plan,
    plan_beat_transition,
)
from .models import AudioTrack
from .slm import SLMTransitionPlan, plan_slm_transition
from .transition import SmartTransitionConfig, clamp, normalize_transition_config

AUTOMIX_VERSION = 1


@dataclass(frozen=True)
class AutoMixPlan:
    crossfade_seconds: float
    current_trim_end: float
    next_trim_start: float
    next_tempo: float
    confidence: float
    reason: str
    beat_plan: BeatTransitionPlan | None = None
    slm_plan: SLMTransitionPlan | None = None


def tempo_ratio_for_bpm(current_bpm: float, next_bpm: float, *, max_adjustment: float = 0.06) -> float:
    """Return a conservative tempo ratio that nudges the next track toward the current track."""

    if current_bpm <= 0 or next_bpm <= 0:
        return 1.0
    next_reference = compatible_next_bpm(current_bpm, next_bpm)
    raw = current_bpm / next_reference
    return clamp(raw, 1.0 - max_adjustment, 1.0 + max_adjustment)


def compatible_next_bpm(current_bpm: float, next_bpm: float) -> float:
    candidates = (next_bpm, next_bpm * 0.5, next_bpm * 2.0)
    return min(candidates, key=lambda candidate: abs(current_bpm - candidate))


def plan_automix_transition(
    current: AudioTrack,
    next_track: AudioTrack,
    current_profile: BeatProfile | None,
    next_profile: BeatProfile | None,
    config: SmartTransitionConfig,
) -> AutoMixPlan:
    """Plan a pair-specific transition and fall back conservatively when analysis is weak."""

    config = normalize_transition_config(config)
    slm_plan = plan_slm_transition(
        current,
        next_track,
        config,
        current_profile=current_profile,
        next_profile=next_profile,
    )
    base_crossfade = slm_plan.crossfade_seconds
    current_trim_end = float(current.trim_end or 0.0)
    next_trim_start = float(next_track.trim_start or 0.0)

    if not current_profile or not next_profile:
        return AutoMixPlan(
            crossfade_seconds=round(base_crossfade, 2),
            current_trim_end=round(current_trim_end, 3),
            next_trim_start=round(next_trim_start, 3),
            next_tempo=1.0,
            confidence=slm_plan.confidence,
            reason="fallback-no-beat-profile",
            slm_plan=slm_plan,
        )

    beat_plan = plan_beat_transition(
        current_profile,
        next_profile,
        base_crossfade_seconds=base_crossfade,
        max_crossfade_seconds=config.max_crossfade_seconds,
    )
    confidence = float(beat_plan.confidence or 0.0)
    if not is_actionable_beat_plan(beat_plan):
        return AutoMixPlan(
            crossfade_seconds=round(min(base_crossfade, beat_plan.crossfade_seconds, 4.0), 2),
            current_trim_end=round(current_trim_end, 3),
            next_trim_start=round(next_trim_start, 3),
            next_tempo=1.0,
            confidence=round(confidence, 3),
            reason=beat_plan.reason,
            beat_plan=beat_plan,
            slm_plan=slm_plan,
        )

    beat_ceiling = (
        slm_plan.crossfade_seconds
        if slm_plan.safety_capped
        else config.max_crossfade_seconds
    )
    crossfade_seconds = clamp(
        min(beat_plan.crossfade_seconds, beat_ceiling),
        0.0,
        config.max_crossfade_seconds,
    )
    duration = float(current.duration or 0.0)
    cue_out = float(beat_plan.current_cue_out or 0.0)
    if duration > 0 and cue_out > 0:
        target_trim_end = max(0.0, duration - cue_out - crossfade_seconds)
        current_trim_end = max(current_trim_end, min(target_trim_end, config.max_outro_trim_seconds))

    cue_in = max(0.0, float(beat_plan.next_cue_in or 0.0))
    next_trim_start = max(next_trim_start, min(cue_in, config.max_intro_trim_seconds))
    next_tempo = tempo_ratio_for_bpm(current_profile.bpm, next_profile.bpm)

    return AutoMixPlan(
        crossfade_seconds=round(crossfade_seconds, 2),
        current_trim_end=round(current_trim_end, 3),
        next_trim_start=round(next_trim_start, 3),
        next_tempo=round(next_tempo, 4),
        confidence=round(confidence, 3),
        reason=f"automix-{beat_plan.reason}",
        beat_plan=beat_plan,
        slm_plan=slm_plan,
    )


def apply_automix_plan(current: AudioTrack, next_track: AudioTrack, plan: AutoMixPlan) -> AutoMixPlan:
    """Apply a pair plan to tracks consumed by ``CrossfadeAudioSource``."""

    current.crossfade_seconds = plan.crossfade_seconds
    current.trim_end = max(float(current.trim_end or 0.0), plan.current_trim_end)
    next_track.trim_start = max(float(next_track.trim_start or 0.0), plan.next_trim_start)
    next_track.tempo = plan.next_tempo
    current.analysis["automix"] = plan_to_dict(plan)
    next_track.analysis["automix"] = {
        "version": AUTOMIX_VERSION,
        "tempo": plan.next_tempo,
        "trim_start": plan.next_trim_start,
        "source": "next",
    }
    return plan


def prepare_automix_transition_pair(
    current: AudioTrack,
    next_track: AudioTrack,
    config: SmartTransitionConfig,
    *,
    current_profile: BeatProfile | None = None,
    next_profile: BeatProfile | None = None,
    analysis_seconds: float = 45.0,
    timeout: float | None = None,
) -> AutoMixPlan:
    """Analyze and apply an AutoMix-style plan for two adjacent tracks."""

    config = normalize_transition_config(config)
    timeout = config.analysis_timeout_seconds if timeout is None else timeout
    if current_profile is None or next_profile is None:
        try:
            if current_profile is None:
                current_profile = analyze_best_source_window(
                    current.stream_url,
                    starts=current_analysis_starts(current, analysis_seconds),
                    duration=analysis_seconds,
                    timeout=timeout,
                )
            if next_profile is None:
                next_profile = analyze_best_source_window(
                    next_track.stream_url,
                    starts=[max(0.0, float(next_track.trim_start or 0.0))],
                    duration=analysis_seconds,
                    timeout=timeout,
                )
        except Exception:
            current_profile = None
            next_profile = None

    plan = plan_automix_transition(current, next_track, current_profile, next_profile, config)
    return apply_automix_plan(current, next_track, plan)


def current_analysis_starts(track: AudioTrack, analysis_seconds: float) -> list[float]:
    duration = float(track.duration or 0.0)
    if duration <= 0:
        return [0.0]
    return [max(0.0, duration - max(1.0, analysis_seconds))]


def plan_to_dict(plan: AutoMixPlan) -> dict:
    data = asdict(plan)
    data["version"] = AUTOMIX_VERSION
    if plan.beat_plan:
        data["beat_plan"] = asdict(plan.beat_plan)
    return data
