# Architecture

Veloura is split into a small set of audio primitives:

- `AudioTrack` stores playable source metadata and transition analysis fields.
- `FFmpegPCMStream` decodes a track into 48 kHz stereo signed 16-bit PCM.
- `CrossfadeAudioSource` mixes the current and next PCM streams with an
  equal-power fade curve and can act as a Discord audio adapter.
- `QueuePlayer` exposes queue controls, frame reads, snapshots, and AutoMix
  pair preparation for apps that are not Discord voice clients. `PCMQueuePlayer`
  remains available as the precise compatibility name.
- `plan_slm_transition` is Veloura's public Small Listening Model planner. It
  chooses automatic pair-specific crossfade seconds locally from duration,
  safety caps, and optional beat profiles.
- `CrossfadeSession` keeps compatibility with older bot integrations that
  manage app-specific queue objects.
- `SmartTransitionConfig` controls silence trimming, loudness normalization, and
  crossfade duration limits.
- `veloura.audio.beat` analyzes beat energy and plans beat-aware transitions.
- `FileAnalysisCache` stores transition analysis in JSON files keyed by source
  and config fingerprints, with optional max-entry and TTL pruning for
  long-running services.

The core package does not own chat commands, database schemas, playlists,
permissions, or UI. Those belong in the app that embeds Veloura.
