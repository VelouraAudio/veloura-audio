"""Ready-made transition presets for common playback environments."""

from __future__ import annotations

from dataclasses import replace

from .transition import SmartTransitionConfig, normalize_transition_config


STREAMER_SAFE = normalize_transition_config(
    SmartTransitionConfig(
        enabled=True,
        base_crossfade_seconds=8.0,
        min_crossfade_seconds=3.0,
        max_crossfade_seconds=12.0,
        analyze_silence=True,
        analyze_trailing_silence=True,
        silence_threshold_db=-45.0,
        silence_duration_seconds=0.35,
        analysis_window_seconds=20.0,
        analysis_timeout_seconds=4.5,
        max_intro_trim_seconds=5.0,
        max_outro_trim_seconds=8.0,
        normalize_loudness=True,
        loudness_target_db=-18.0,
        loudness_min_gain=0.70,
        loudness_max_gain=1.25,
        loudness_analysis_seconds=24.0,
    )
)

BROADCAST_SMOOTH = normalize_transition_config(
    replace(
        STREAMER_SAFE,
        base_crossfade_seconds=10.0,
        min_crossfade_seconds=4.0,
        max_crossfade_seconds=15.0,
        loudness_target_db=-17.0,
    )
)

LOW_LATENCY = normalize_transition_config(
    replace(
        STREAMER_SAFE,
        base_crossfade_seconds=5.0,
        min_crossfade_seconds=2.0,
        max_crossfade_seconds=8.0,
        analyze_trailing_silence=False,
        analysis_window_seconds=12.0,
        analysis_timeout_seconds=2.0,
        loudness_analysis_seconds=12.0,
    )
)

PRESETS = {
    "streamer": STREAMER_SAFE,
    "streamer-safe": STREAMER_SAFE,
    "broadcast": BROADCAST_SMOOTH,
    "broadcast-smooth": BROADCAST_SMOOTH,
    "low-latency": LOW_LATENCY,
    "fast": LOW_LATENCY,
}


def preset_names() -> tuple[str, ...]:
    return tuple(sorted(PRESETS))


def transition_preset(name: str = "streamer") -> SmartTransitionConfig:
    key = (name or "streamer").strip().lower()
    try:
        return PRESETS[key]
    except KeyError as exc:
        available = ", ".join(preset_names())
        raise ValueError(f"Unknown Veloura preset '{name}'. Available presets: {available}.") from exc
