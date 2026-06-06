# Veloura Scope

Veloura is a reusable Python audio transition engine. The Discord bot is one
consumer of the package, not the package's identity.

## Target Use Cases

- Streamer background music engines
- 24/7 radio or livestream music pipelines
- Discord, Twitch, or web music bots
- Desktop music tools that need smooth queue playback
- Audio automation scripts that need predictable fades and gain control

## Core Package Owns

- Audio track models
- PCM helpers
- FFmpeg-backed PCM decoding
- Equal-power crossfade mixing
- Queue/session buffering
- Silence trim analysis
- Loudness normalization
- Beat/BPM analysis
- Beat-aware transition planning
- Stream URL resolution helpers
- Presets for streamer, broadcast, and low-latency modes
- File-based transition analysis cache
- CLI tools for local analysis and transition planning

## Core Package Does Not Own

- Discord buttons, views, embeds, slash commands, or permissions
- Lavalink nodes
- Guild/server state
- User playlists and saved songs
- Spotify, Apple Music, Deezer, or Tidal scraping
- Bot banners and presence
- Database schemas for a specific app

## Public API Direction

Prefer these public names for new projects:

- `AudioTrack`
- `CrossfadeSession`
- `FileAnalysisCache`
- `transition_preset`
- `prepare_smart_transition`
- `plan_beat_transition`
- `resolve_stream_track`

Keep these names for compatibility:

- `MixerTrack`
- `CrossfadeAudioSource`

## Release Milestones

### 0.3

- Generic `AudioTrack` public model
- Streamer/broadcast/low-latency presets
- `python -m veloura` CLI
- File-based transition analysis cache
- Generated audio tests for trim/loudness behavior
- Docs for non-Discord use

### 0.4

- Example streamer player script
- Cleaner status/snapshot model for external UIs
- Optional playback adapters

### 0.5

- Stronger beat-aware planning
- Better confidence scoring
- Safer automatic fallback decisions
- Transition preview/export helpers

### 1.0

- Stable typed API
- Backward-compatible migration notes
- Separate docs site/package README
- Published package ready for public use
