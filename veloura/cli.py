"""Command line helpers for Veloura."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any

from .audio import (
    AudioTrack,
    FileAnalysisCache,
    analyze_best_source_window,
    compact_profile_to_dict,
    plan_beat_transition,
    preset_names,
    prepare_smart_transition,
    resolve_stream_track,
    transition_preset,
)
from .audio.beat import analyze_source, plan_to_dict


def cache_from_args(args: argparse.Namespace) -> FileAnalysisCache | None:
    if getattr(args, "no_cache", False):
        return None
    return FileAnalysisCache(getattr(args, "cache_dir", None))


def track_to_dict(track: AudioTrack) -> dict[str, Any]:
    return {
        "title": track.title,
        "artist": track.artist,
        "album": track.album,
        "webpage": track.webpage,
        "duration": track.duration,
        "trim_start": round(float(track.trim_start or 0.0), 3),
        "trim_end": round(float(track.trim_end or 0.0), 3),
        "gain": round(float(track.gain or 1.0), 4),
        "crossfade_seconds": track.crossfade_seconds,
        "analysis": track.analysis,
    }


async def resolve_track(args: argparse.Namespace) -> int:
    config = transition_preset(args.preset) if args.prepare else None
    track = await resolve_stream_track(
        args.query,
        fallback_title=args.title,
        transition_config=config,
        analysis_cache=cache_from_args(args) if config else None,
    )
    print(json.dumps(track_to_dict(track), indent=2))
    return 0


def analyze_track(args: argparse.Namespace) -> int:
    profile = analyze_source(
        args.source,
        start_at=args.start,
        duration=args.duration,
        timeout=args.timeout,
    )
    print(json.dumps(compact_profile_to_dict(profile), indent=2))
    return 0


async def plan_transition(args: argparse.Namespace) -> int:
    config = transition_preset(args.preset)
    current_source = args.current
    next_source = args.next
    analysis_cache = cache_from_args(args)

    if args.resolve:
        current_track = await resolve_stream_track(args.current, transition_config=config, analysis_cache=analysis_cache)
        next_track = await resolve_stream_track(args.next, transition_config=config, analysis_cache=analysis_cache)
        current_source = current_track.stream_url
        next_source = next_track.stream_url

    current_profile = analyze_best_source_window(
        current_source,
        starts=[args.current_start],
        duration=args.duration,
        timeout=args.timeout,
    )
    next_profile = analyze_best_source_window(
        next_source,
        starts=[args.next_start],
        duration=args.duration,
        timeout=args.timeout,
    )
    plan = plan_beat_transition(
        current_profile,
        next_profile,
        base_crossfade_seconds=config.base_crossfade_seconds,
        max_crossfade_seconds=config.max_crossfade_seconds,
    )
    print(
        json.dumps(
            {
                "preset": args.preset,
                "current": compact_profile_to_dict(current_profile),
                "next": compact_profile_to_dict(next_profile),
                "plan": plan_to_dict(plan),
            },
            indent=2,
        )
    )
    return 0


def prepare_track(args: argparse.Namespace) -> int:
    config = transition_preset(args.preset)
    track = AudioTrack.from_source(
        args.source,
        title=args.title,
        duration=args.duration,
    )
    analysis_cache = cache_from_args(args)
    if analysis_cache:
        analysis_cache.prepare_transition(track, config)
    else:
        prepare_smart_transition(track, config)
    print(json.dumps(track_to_dict(track), indent=2))
    return 0


def list_presets(_: argparse.Namespace) -> int:
    print("\n".join(preset_names()))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="veloura",
        description="Veloura audio transition engine tools.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    presets = subparsers.add_parser("presets", help="List built-in transition presets.")
    presets.set_defaults(func=list_presets)

    resolve = subparsers.add_parser("resolve", help="Resolve a query or URL into a playable track.")
    resolve.add_argument("query")
    resolve.add_argument("--title")
    resolve.add_argument("--preset", default="streamer")
    resolve.add_argument("--no-prepare", action="store_false", dest="prepare")
    resolve.add_argument("--cache-dir")
    resolve.add_argument("--no-cache", action="store_true")
    resolve.set_defaults(func=lambda args: asyncio.run(resolve_track(args)))

    prepare = subparsers.add_parser("prepare", help="Analyze trim, loudness, and transition settings for a source.")
    prepare.add_argument("source")
    prepare.add_argument("--title")
    prepare.add_argument("--duration", type=float)
    prepare.add_argument("--preset", default="streamer")
    prepare.add_argument("--cache-dir")
    prepare.add_argument("--no-cache", action="store_true")
    prepare.set_defaults(func=prepare_track)

    analyze = subparsers.add_parser("analyze", help="Analyze BPM and beats for a local file or direct stream URL.")
    analyze.add_argument("source")
    analyze.add_argument("--start", type=float, default=0.0)
    analyze.add_argument("--duration", type=float, default=45.0)
    analyze.add_argument("--timeout", type=float, default=12.0)
    analyze.set_defaults(func=analyze_track)

    plan = subparsers.add_parser("plan", help="Plan a beat-aware transition between two sources.")
    plan.add_argument("current")
    plan.add_argument("next")
    plan.add_argument("--preset", default="streamer")
    plan.add_argument("--resolve", action="store_true", help="Resolve inputs with yt-dlp before analysis.")
    plan.add_argument("--current-start", type=float, default=0.0)
    plan.add_argument("--next-start", type=float, default=0.0)
    plan.add_argument("--duration", type=float, default=45.0)
    plan.add_argument("--timeout", type=float, default=12.0)
    plan.add_argument("--cache-dir")
    plan.add_argument("--no-cache", action="store_true")
    plan.set_defaults(func=lambda args: asyncio.run(plan_transition(args)))

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except RuntimeError as exc:
        print(f"veloura: {exc}", file=sys.stderr)
        return 1
