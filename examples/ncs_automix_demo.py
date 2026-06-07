#!/usr/bin/env python3
"""Play an AutoMix demo with official NCS source URLs.

The tracks are not bundled with Veloura. This example resolves the official
NCS YouTube uploads locally, prepares an AutoMix transition pair, and pipes
Veloura's PCM output to ffplay.
"""

from __future__ import annotations

import argparse
import asyncio
import shutil
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
    FileAnalysisCache,
    PCMQueuePlayer,
    prepare_automix_transition_pair,
    prepare_smart_transition,
    resolve_stream_track,
    transition_preset,
)

WHERE_WE_STARTED_URL = "https://www.youtube.com/watch?v=U9pGr6KMdyg"
FEARLESS_PT_II_URL = "https://www.youtube.com/watch?v=S19UcWdOA-I"

NCS_CREDITS = (
    "Song: Lost Sky - Where We Started (feat. Jex) [NCS Release]\n"
    "Music provided by NoCopyrightSounds\n"
    "Free Download/Stream: http://ncs.io/WhereWeStarted\n"
    "Watch: http://youtu.be/U9pGr6KMdyg\n\n"
    "Song: TULE - Fearless pt.II (feat. Chris Linton) [NCS Release]\n"
    "Music provided by NoCopyrightSounds\n"
    "Free Download/Stream: http://ncs.io/Fearless2\n"
    "Watch: http://youtu.be/S19UcWdOA-I"
)


def probe_duration(source: str) -> float:
    ffprobe = shutil.which("ffprobe")
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


def open_ffplay() -> subprocess.Popen:
    ffplay = shutil.which("ffplay")
    if not ffplay:
        raise RuntimeError("ffplay was not found. Install FFmpeg with ffplay to run this example.")
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


def play_tracks(tracks: list[AudioTrack], *, volume: float, crossfade: float) -> None:
    player = PCMQueuePlayer(volume=volume, crossfade_seconds=crossfade)
    player.extend(tracks)

    ffplay = open_ffplay()
    try:
        while True:
            frame = player.read_frame()
            if not frame or not ffplay.stdin:
                break
            ffplay.stdin.write(frame)
    finally:
        player.stop()
        if ffplay.stdin:
            ffplay.stdin.close()
        ffplay.wait(timeout=5)


async def run_demo(args: argparse.Namespace) -> list[AudioTrack]:
    cache = None if args.no_cache else FileAnalysisCache(args.cache_dir)
    tracks = [
        await build_track(source, preset=args.preset, cache=cache)
        for source in args.sources
    ]
    if len(tracks) >= 2:
        config = transition_preset(args.preset)
        await asyncio.to_thread(prepare_automix_transition_pair, tracks[0], tracks[1], config)
    return tracks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Play a Veloura AutoMix demo with official NCS URLs.")
    parser.add_argument(
        "sources",
        nargs="*",
        default=[WHERE_WE_STARTED_URL, FEARLESS_PT_II_URL],
        help="Optional local files, stream URLs, or yt-dlp queries. Defaults to two official NCS uploads.",
    )
    parser.add_argument("--preset", default="automix")
    parser.add_argument("--volume", type=float, default=0.65)
    parser.add_argument("--crossfade", type=float, default=9.0)
    parser.add_argument("--cache-dir")
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--print-credits", action="store_true")
    args = parser.parse_args(argv)

    if args.print_credits:
        print(NCS_CREDITS)

    tracks = asyncio.run(run_demo(args))
    play_tracks(tracks, volume=args.volume, crossfade=args.crossfade)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
