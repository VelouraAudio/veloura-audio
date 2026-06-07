# Veloura

Veloura is a reusable Python audio transition engine for smooth queue playback.
It provides FFmpeg-backed PCM decoding, equal-power crossfades, transition
analysis, beat-aware planning, and a small CLI for local inspection.

Veloura is framework-agnostic. Use it in streamer tools, radio pipelines,
desktop music apps, Discord/Twitch bots, or backend automation without tying
your project to one bot implementation.

## Features

- Equal-power crossfade mixing for signed 16-bit PCM audio
- Discord-independent PCM queue player with snapshots and playback controls
- Smart transition planning based on track duration, silence trim, and loudness
- Beat/BPM analysis with beat-aware transition plans
- Project-local or user-cache transition analysis storage
- Optional `yt-dlp` stream resolution for URLs and search queries
- Optional Discord audio source compatibility
- Pure-Python PCM fallback for Python builds without `audioop`

## Requirements

- Python 3.12 or newer
- FFmpeg for decoding, playback, silence analysis, loudness analysis, and beat
  analysis
- `yt-dlp` only when resolving online stream/search inputs
- `discord.py` and `PyNaCl` only when using the Discord audio source directly

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
python -m veloura prepare ./song.mp3 --preset streamer
python -m veloura analyze ./song.mp3
python -m veloura plan ./current.mp3 ./next.mp3 --preset broadcast
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

## Standalone Example

The example player resolves local files or stream queries, prepares transition
analysis, mixes the queue, and pipes PCM into `ffplay`:

```bash
python examples/streamer_player.py ./song-a.mp3 ./song-b.mp3 --preset streamer
python examples/streamer_player.py ./song-a.mp3 ./song-b.mp3 --cache-dir ./veloura-cache
```

## Free Transition Demo

The website includes a small transition clip rendered from CC0 music sources
with `PCMQueuePlayer`. Regenerate it with:

```bash
python examples/generate_transition_demo_audio.py
```

Demo music sources:

- Empacotatron by Fupi: <https://opengameart.org/content/empacotatron>
- Rhythm Garden by congusbongus: <https://opengameart.org/content/rhythm-garden>

Both source pages list the license as CC0. Attribution is not required by CC0,
but Veloura credits the sources so the demo has clear provenance.
