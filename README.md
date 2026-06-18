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

## 0.6.2 Hardening Snapshot

| Area | Fixed behavior |
| --- | --- |
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

## Quick Start

```python
from veloura.audio import AudioTrack, PCMQueuePlayer, transition_preset

config = transition_preset("streamer")

track = AudioTrack.from_source(
    "/music/current-song.flac",
    title="Artist - Current Song",
    duration=184,
)

player = PCMQueuePlayer(volume=0.65, crossfade_seconds=config.base_crossfade_seconds)
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

Aliases such as `streamer-safe`, `broadcast-smooth`, `auto-mix`, and `fast` are also
available.

For adjacent tracks, call `prepare_automix_transition_pair` before playback of
the next track starts. It analyzes beat windows, applies a pair-specific
crossfade length, trims weak intro audio on confident matches, and nudges tempo
only within a small safe range.

Apps that manage playback through `PCMQueuePlayer` can call
`player.prepare_next_transition_pair(...)` when the current and next track are
known. Discord bots can keep using `CrossfadeAudioSource` as an adapter for
Discord voice playback.

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
source = CrossfadeAudioSource(crossfade_seconds=config.base_crossfade_seconds)

track = await resolve_stream_track(
    "artist song official audio",
    transition_config=config,
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

For public bots, treat user search terms and URLs as untrusted input. Keep
permission checks in the bot, rate-limit stream resolution, and avoid exposing
`yt-dlp` resolution to users who should not be able to trigger network lookups.

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
sources. One demo is rendered through `PCMQueuePlayer`; the lossless demo is
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
- Install system FFmpeg if you want to use the standalone `ffplay` example.
- Install `veloura-audio[stream]` when resolving YouTube URLs or search
  queries through `yt-dlp`.
- Install `veloura-audio[discord]` when using `CrossfadeAudioSource` directly
  with Discord voice playback.
- Run `python -m veloura presets` to confirm the CLI entry point is installed.
