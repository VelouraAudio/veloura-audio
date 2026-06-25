# Veloura

Veloura is a reusable Python audio transition engine for smooth queue playback.
It provides FFmpeg-backed PCM decoding, equal-power crossfades, transition
analysis, beat-aware planning, and a small CLI for local inspection.

Veloura is framework-agnostic. Use it in streamer tools, radio pipelines,
desktop music apps, Discord/Twitch bots, or backend automation without tying
your project to one bot implementation.

## Features

- Equal-power crossfade mixing for signed 16-bit PCM audio
- Lossless file transition rendering to FLAC, WAV, ALAC, or AIFF
- Discord-independent PCM queue player with snapshots and playback controls
- Public Small Listening Model planner for automatic pair-specific crossfade timing
- Smart transition planning based on track duration, silence trim, and loudness
- Beat/BPM analysis with beat-aware transition plans
- Project-local or user-cache transition analysis storage
- Optional `yt-dlp` stream resolution for URLs and search queries
- Optional Discord audio source compatibility
- Pure-Python PCM fallback for Python builds without `audioop`

## Requirements

- Python 3.12 or newer
- Veloura installs `imageio-ffmpeg` by default and uses its bundled FFmpeg
  executable when system `ffmpeg` is not available
- System `ffplay` is only needed for the standalone local player example
- `yt-dlp` only when resolving online stream/search inputs
- `discord.py` and `PyNaCl` only when using the Discord audio source directly

## 0.6.5 SLM Auto Timing Snapshot

| Area | What changed |
| --- | --- |
| Small Listening Model | Added `plan_slm_transition(...)` for automatic crossfade timing without manual seconds. |
| AutoMix | AutoMix now uses the SLM timing estimate before beat-aware refinement. |
| Presets | `slm` and `veloura-auto` aliases map to the AutoMix configuration for automatic pair planning. |
| Public player API | `QueuePlayer` is now the friendly import name for app playback; `PCMQueuePlayer` remains supported. |
| Onboarding | Docs now explain the PyPI package name (`veloura-audio`) versus the Python import name (`veloura`). |
| AutoMix docs | Module-level pair preparation and player queue helpers are documented as separate use cases. |
| Preset docs | Canonical presets are shown first, with compatibility aliases kept out of the main path. |
| Playback failures | Bad FFmpeg streams now surface through queue snapshot errors instead of disappearing silently. |
| CLI health checks | `python -m veloura doctor` rejects invalid configured FFmpeg paths. |
| Cross-platform playback | PCM stream reads no longer depend on Unix-only pipe `select()` behavior. |
| Short clips | Crossfade lengths are bounded for very short tracks and lossless renders. |
| Lossless renders | Prepared gain and tempo settings are applied in file renders. |
| Cache safety | Corrupt transition cache values are ignored instead of crashing preparation. |
| Metadata | `AudioTrack.from_source()` now maps common fields like `artist` and `album` directly. |

## Installation

Install the core package:

```bash
pip install veloura-audio
```

Install stream resolution support:

```bash
pip install "veloura-audio[stream]"
```

Install Discord voice support:

```bash
pip install "veloura-audio[discord]"
```

Install every optional integration:

```bash
pip install "veloura-audio[all]"
```

Verify the installed package:

```bash
python -c "import veloura; print(veloura.__version__)"
python -m veloura doctor
```

The PyPI distribution is named `veloura-audio`; the Python import package is
`veloura`:

```python
import veloura
from veloura.audio import AudioTrack, QueuePlayer
```

## Quick Start

```python
from veloura.audio import AudioTrack, QueuePlayer, transition_preset

config = transition_preset("streamer")

track = AudioTrack.from_source(
    "/music/current-song.flac",
    title="Artist - Current Song",
    duration=184,
)

player = QueuePlayer(volume=0.65, crossfade_seconds=config.base_crossfade_seconds)
player.enqueue(track)

frame = player.read_frame()
```

For online sources, install `veloura-audio[stream]` and resolve a playable stream:

```python
import asyncio

from veloura.audio import resolve_stream_track, transition_preset


async def main():
    track = await resolve_stream_track(
        "artist song official audio",
        transition_config=transition_preset("streamer"),
    )
    print(track.title, track.stream_url)


asyncio.run(main())
```

## CLI

Veloura exposes the same core tools through `python -m veloura` or the
`veloura` console script:

```bash
python -m veloura presets
python -m veloura doctor
python -m veloura prepare ./song.mp3 --preset streamer
python -m veloura analyze ./song.mp3
python -m veloura plan ./current.mp3 ./next.mp3 --preset broadcast
python -m veloura render-transition ./song-a.flac ./song-b.flac ./transition.flac
```

For YouTube/search inputs, install `veloura-audio[stream]` and add `--resolve`:

```bash
python -m veloura plan "current song" "next song" --preset streamer --resolve
```

Transition analysis is cached under `~/.cache/veloura` by default, or under the
directory set in `VELOURA_CACHE_DIR`. Use `--cache-dir` for a project-local
cache, or `--no-cache` when comparing fresh analysis.

## Presets

- `streamer`: balanced transitions for livestream/background music
- `broadcast`: longer, smoother radio-style blends
- `low-latency`: shorter analysis windows for weaker machines or fast queues
- `automix`: beat-aware pair planning with conservative tempo matching

Compatibility aliases such as `streamer-safe`, `broadcast-smooth`,
`auto-mix`, `slm`, `veloura-auto`, and `fast` remain available for older
integrations.

## Veloura SLM Auto Timing

Veloura's public SLM means **Small Listening Model**. It is deterministic,
local-only, and does not call any external AI service. It chooses a pair-specific
crossfade duration from track duration, safety caps, and optional beat profiles:

```python
from veloura.audio import AudioTrack, plan_slm_transition, transition_preset

config = transition_preset("slm")
current = AudioTrack.from_source("track-a.flac", title="Track A", duration=184)
next_track = AudioTrack.from_source("track-b.flac", title="Track B", duration=196)

plan = plan_slm_transition(current, next_track, config)
print(plan.crossfade_seconds, plan.reason)
```

Use this when your app wants Veloura to choose transition timing instead of
asking users to set `crossfade_seconds` by hand.

Use `prepare_automix_transition_pair(...)` when you have two explicit
`AudioTrack` objects and want to prepare their transition before playback. It
analyzes beat windows, applies a pair-specific crossfade length, trims weak
intro audio on confident matches, uses the SLM crossfade estimate, and nudges
tempo only within a small safe range.

Apps that manage playback through `QueuePlayer` can call
`player.prepare_next_transition_pair(...)` as a queue convenience method when
the current and next track are already inside the player. Discord bots can keep
using `CrossfadeAudioSource` as an adapter for Discord voice playback.

## Lossless Transition Rendering

For local renderers, music apps, and release-prep workflows, Veloura can render
two sources into a lossless transition file:

```bash
python -m veloura render-transition ./track-a.flac ./track-b.flac ./transition.flac --crossfade 8
```

Supported output extensions are `.flac`, `.wav`, `.m4a`, `.alac`, `.aif`, and
`.aiff`. The renderer decodes inputs to high-precision float PCM inside FFmpeg,
uses an equal-power-style crossfade curve, and writes a lossless output codec.

Programmatic use:

```python
from veloura.audio import LosslessTransitionConfig, render_lossless_transition

render_lossless_transition(
    "track-a.flac",
    "track-b.flac",
    "transition.flac",
    LosslessTransitionConfig(crossfade_seconds=8),
)
```

This is lossless file transition processing, not bit-perfect copying, because
crossfading intentionally changes the waveform. Discord voice output is still
encoded by Discord.

## Discord Bot Integration

Keep your bot commands, queue state, and permissions in your Discord project.
Use Veloura as the audio transition layer:

```python
from veloura.audio import CrossfadeAudioSource, resolve_stream_track, transition_preset

config = transition_preset("streamer")
source = CrossfadeAudioSource(
    crossfade_seconds=config.base_crossfade_seconds,
    max_queue_size=50,
)

track = await resolve_stream_track(
    "artist song official audio",
    transition_config=config,
    timeout=35,
)

source.enqueue(track)
voice_client.play(source)
```

### Slash Command Example

Veloura includes a minimal Discord slash-command bot at
`examples/discord_slash_bot.py`. It provides `/play`, `/queue`, `/now`, `/skip`,
`/stop`, and `/volume`.

```bash
pip install "veloura-audio[all]"
export DISCORD_TOKEN="your-bot-token"
export DISCORD_GUILD_ID="your-test-server-id"
python examples/discord_slash_bot.py
```

`DISCORD_GUILD_ID` is optional, but recommended for development because server
slash-command sync is much faster than global sync.

When inviting the bot, enable the `bot` and `applications.commands` scopes and
grant Connect/Speak voice permissions.

The example includes public-bot guardrails: same-voice-channel controls,
optional DJ role checks, mention escaping, queue caps, per-user `/play`
cooldowns, resolver timeouts, and bounded analysis cache storage. Useful
environment variables:

- `VELOURA_DJ_ROLE_ID`: require a Discord role for `/play`, `/skip`, `/stop`,
  and `/volume`.
- `VELOURA_MAX_QUEUE_SIZE`: cap pending tracks per server. Default: `50`.
- `VELOURA_PLAY_COOLDOWN_SECONDS`: per-user `/play` cooldown. Default: `5`.
- `VELOURA_RESOLVE_TIMEOUT_SECONDS`: cap stream lookup and analysis waits.
  Default: `35`.
- `VELOURA_CACHE_MAX_ENTRIES`: cap transition analysis cache files. Default:
  `1000`.
- `VELOURA_CACHE_TTL_SECONDS`: expire old cache files. Default: `604800`.

For public bots, still treat user search terms and URLs as untrusted input.
Keep permission checks in your app, rate-limit stream resolution, and avoid
exposing `yt-dlp` resolution to users who should not be able to trigger network
lookups.

## Standalone Example

The example player resolves local files or stream queries, prepares transition
analysis, mixes the queue, and pipes PCM into `ffplay`. This example needs a
system FFmpeg install with `ffplay` available:

```bash
python examples/streamer_player.py ./song-a.mp3 ./song-b.mp3 --preset streamer
python examples/streamer_player.py ./song-a.mp3 ./song-b.mp3 --cache-dir ./veloura-cache
```

## Free Transition Demos

The website includes small playable transition clips rendered from CC0 music
sources. One demo is rendered through `QueuePlayer`; the lossless demo is
rendered through `python -m veloura render-transition` into FLAC and WAV output.
Regenerate them with:

```bash
python examples/generate_transition_demo_audio.py
```

Demo music sources:

- Empacotatron by Fupi: <https://opengameart.org/content/empacotatron>
- Rhythm Garden by congusbongus: <https://opengameart.org/content/rhythm-garden>

Both source pages list the license as CC0. Attribution is not required by CC0,
but Veloura credits the sources so the demo has clear provenance.

## Troubleshooting

- Run `python -m veloura doctor` to verify FFmpeg and optional integrations.
- Set `VELOURA_FFMPEG=/path/to/ffmpeg` if you want Veloura to use a specific
  FFmpeg executable instead of the bundled provider.
- Set `VELOURA_YTDLP_SOURCE_ADDRESS` only when you need `yt-dlp` to use a
  specific outbound network interface.
- Pass `max_queue_size` to `CrossfadeAudioSource` or `QueuePlayer` when the
  queue is exposed to public users.
- Use `FileAnalysisCache(max_entries=..., ttl_seconds=...)` for long-running
  bots or services.
- Install system FFmpeg if you want to use the standalone `ffplay` example.
- Install `veloura-audio[stream]` when resolving YouTube URLs or search
  queries through `yt-dlp`.
- Install `veloura-audio[discord]` when using `CrossfadeAudioSource` directly
  with Discord voice playback.
- Run `python -m veloura presets` to confirm the CLI entry point is installed.
