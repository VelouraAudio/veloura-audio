"""Audio engine primitives for Veloura."""

from .constants import (
    CHANNELS,
    FRAME_BYTES,
    FRAME_DURATION,
    FRAME_RATE,
    MIXER_CROSSFADE_SECONDS,
    MIXER_DEFAULT_VOLUME,
    SAMPLE_WIDTH,
    YDL_STREAM_OPTIONS,
)
from .beat import (
    DEFAULT_FRAME_SECONDS,
    BeatProfile,
    BeatTransitionPlan,
    analyze_best_source_window,
    analyze_beats_from_energy,
    compact_profile_to_dict,
    is_actionable_beat_plan,
    plan_beat_transition,
    profile_from_dict,
    profile_to_dict,
    synthetic_pulse_energy,
    unique_starts,
)
from .automix import (
    AutoMixPlan,
    apply_automix_plan,
    current_analysis_starts,
    plan_automix_transition,
    prepare_automix_transition_pair,
    tempo_ratio_for_bpm,
)
from .cache import (
    FileAnalysisCache,
    build_transition_cache_key,
    default_cache_dir,
)
from .crossfade import CrossfadeAudioSource
from .ffmpeg_stream import FFmpegPCMStream
from .models import AudioTrack, MixerTrack
from .pcm import pcm_add, pcm_mul, pcm_rms
from .player import PCMQueuePlayer, QueueSnapshot
from .presets import (
    AUTOMIX,
    BROADCAST_SMOOTH,
    LOW_LATENCY,
    STREAMER_SAFE,
    preset_names,
    transition_preset,
)
from .resolver import resolve_stream_track
from .session import CrossfadeAdvance, CrossfadeSession
from .transition import (
    LoudnessProfile,
    SilenceProfile,
    SmartTransitionConfig,
    normalize_transition_config,
    planned_crossfade_seconds,
    prepare_smart_transition,
)

__all__ = [
    "CHANNELS",
    "FRAME_BYTES",
    "FRAME_DURATION",
    "FRAME_RATE",
    "MIXER_CROSSFADE_SECONDS",
    "MIXER_DEFAULT_VOLUME",
    "SAMPLE_WIDTH",
    "YDL_STREAM_OPTIONS",
    "DEFAULT_FRAME_SECONDS",
    "BeatProfile",
    "BeatTransitionPlan",
    "analyze_best_source_window",
    "analyze_beats_from_energy",
    "compact_profile_to_dict",
    "is_actionable_beat_plan",
    "plan_beat_transition",
    "profile_from_dict",
    "profile_to_dict",
    "synthetic_pulse_energy",
    "unique_starts",
    "AutoMixPlan",
    "apply_automix_plan",
    "current_analysis_starts",
    "plan_automix_transition",
    "prepare_automix_transition_pair",
    "tempo_ratio_for_bpm",
    "FileAnalysisCache",
    "build_transition_cache_key",
    "default_cache_dir",
    "CrossfadeAudioSource",
    "FFmpegPCMStream",
    "AudioTrack",
    "MixerTrack",
    "pcm_add",
    "pcm_mul",
    "pcm_rms",
    "PCMQueuePlayer",
    "QueueSnapshot",
    "AUTOMIX",
    "BROADCAST_SMOOTH",
    "LOW_LATENCY",
    "STREAMER_SAFE",
    "preset_names",
    "transition_preset",
    "resolve_stream_track",
    "CrossfadeAdvance",
    "CrossfadeSession",
    "LoudnessProfile",
    "SilenceProfile",
    "SmartTransitionConfig",
    "normalize_transition_config",
    "planned_crossfade_seconds",
    "prepare_smart_transition",
]
