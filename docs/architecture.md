# Architecture

Veloura is split into a small set of audio primitives:

- `AudioTrack` stores playable source metadata and transition analysis fields.
- `FFmpegPCMStream` decodes a track into 48 kHz stereo signed 16-bit PCM.
- `CrossfadeAudioSource` mixes the current and next PCM streams with an
  equal-power fade curve.
- `CrossfadeSession` manages queue buffering, current-track state, skips, and
  snapshots for external apps.
- `SmartTransitionConfig` controls silence trimming, loudness normalization, and
  crossfade duration limits.
- `veloura.audio.beat` analyzes beat energy and plans beat-aware transitions.
- `FileAnalysisCache` stores transition analysis in JSON files keyed by source
  and config fingerprints.

The core package does not own chat commands, database schemas, playlists,
permissions, or UI. Those belong in the app that embeds Veloura.
