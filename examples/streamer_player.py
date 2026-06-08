#!/usr/bin/env python3
"""Minimal standalone streamer player powered by Veloura.

This example does not import the Discord bot. It resolves each argument into an
audio track, applies Veloura transition analysis, then pipes mixed PCM into
``ffplay``.

Example:

    python examples/streamer_player.py "./song-a.mp3" "./song-b.mp3"
"""

from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from veloura.audio import (
    CHANNELS,
    FRAME_RATE,
    AudioTrack,
    CrossfadeSession,
    FileAnalysisCache,
    prepare_smart_transition,
    resolve_stream_track,
    transition_preset,
)
from veloura.audio.ffmpeg_binary import resolve_ffplay, resolve_ffprobe


def probe_duration(source: str) -> float:
    ffprobe = resolve_ffprobe()
    if not ffprobe:
        return 0.0
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            source,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
    )
    try:
        return float((result.stdout or "0").strip() or 0.0)
    except ValueError:
        return 0.0


async def build_track(source: str, *, preset: str, cache: FileAnalysisCache | None) -> AudioTrack:
    config = transition_preset(preset)
    if Path(source).exists():
        track = AudioTrack.from_source(
            source,
            title=Path(source).stem,
            duration=probe_duration(source),
        )
        if cache:
            return await asyncio.to_thread(cache.prepare_transition, track, config)
        return await asyncio.to_thread(prepare_smart_transition, track, config)
    return await resolve_stream_track(source, transition_config=config, analysis_cache=cache)


async def build_tracks(
    sources: list[str],
    *,
    preset: str,
    cache: FileAnalysisCache | None,
) -> list[AudioTrack]:
    return [await build_track(source, preset=preset, cache=cache) for source in sources]


def open_ffplay() -> subprocess.Popen:
    ffplay = resolve_ffplay()
    if not ffplay:
        raise RuntimeError("ffplay was not found. Install system FFmpeg with ffplay to run this example.")
    return subprocess.Popen(
        [
            ffplay,
            "-nodisp",
            "-autoexit",
            "-loglevel",
            "warning",
            "-f",
            "s16le",
            "-ar",
            str(FRAME_RATE),
            "-ac",
            str(CHANNELS),
            "-i",
            "pipe:0",
        ],
        stdin=subprocess.PIPE,
    )


def play_tracks(tracks: list[AudioTrack], *, volume: float, crossfade: float):
    session = CrossfadeSession(volume=volume, crossfade_seconds=crossfade)
    for track in tracks:
        session.source.enqueue(track)

    player = open_ffplay()
    try:
        while True:
            frame = session.source.read()
            if not frame:
                break
            if not player.stdin:
                break
            player.stdin.write(frame)
    finally:
        session.stop()
        if player.stdin:
            player.stdin.close()
        player.wait(timeout=5)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Play a Veloura-powered streamer queue.")
    parser.add_argument("sources", nargs="+", help="Local files, stream URLs, or yt-dlp search queries.")
    parser.add_argument("--preset", default="streamer")
    parser.add_argument("--volume", type=float, default=0.65)
    parser.add_argument("--crossfade", type=float, default=8.0)
    parser.add_argument("--cache-dir")
    parser.add_argument("--no-cache", action="store_true")
    args = parser.parse_args(argv)

    cache = None if args.no_cache else FileAnalysisCache(args.cache_dir)
    tracks = asyncio.run(build_tracks(args.sources, preset=args.preset, cache=cache))
    play_tracks(tracks, volume=args.volume, crossfade=args.crossfade)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
