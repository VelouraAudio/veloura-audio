#!/usr/bin/env python3
"""Generate the public CC0 music transition demo for GitHub Pages."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import urllib.error
import wave
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from veloura.audio import (
    AudioTrack,
    FRAME_RATE,
    LosslessTransitionConfig,
    QueuePlayer,
    render_lossless_transition,
)
from veloura.audio.ffmpeg_binary import require_ffmpeg

CHANNELS = 2
SAMPLE_WIDTH = 2
FRAME_DURATION = 0.02
CLIP_SECONDS = 9.0
CROSSFADE_SECONDS = 4.0
OUTPUT_SECONDS_LIMIT = 16.0
USER_AGENT = "veloura-audio-demo/0.6.5"
DEFAULT_QUEUE_OUTPUT = PROJECT_ROOT / "docs" / "assets" / "veloura-transition-demo.wav"
DEFAULT_LOSSLESS_OUTPUT = PROJECT_ROOT / "docs" / "assets" / "veloura-lossless-transition-demo.wav"
DEFAULT_LOSSLESS_FLAC_OUTPUT = PROJECT_ROOT / "docs" / "assets" / "veloura-lossless-transition-demo.flac"
ALLOWED_DEMO_HOST = "opengameart.org"


@dataclass(frozen=True)
class DemoSource:
    title: str
    author: str
    page_url: str
    filename: str
    start_seconds: float


SOURCES = (
    DemoSource(
        title="Empacotatron",
        author="Fupi",
        page_url="https://opengameart.org/content/empacotatron",
        filename="empacotatron_full.ogg",
        start_seconds=6.0,
    ),
    DemoSource(
        title="Rhythm Garden",
        author="congusbongus",
        page_url="https://opengameart.org/content/rhythm-garden",
        filename="rhythm_garden.ogg",
        start_seconds=10.0,
    ),
)


class AttachmentLinkParser(HTMLParser):
    def __init__(self, filename: str):
        super().__init__()
        self.filename = filename
        self._href: str | None = None
        self.match: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        self._href = dict(attrs).get("href")

    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            self._href = None

    def handle_data(self, data: str) -> None:
        if self.match or not self._href:
            return
        if data.strip() == self.filename:
            self.match = self._href


def validate_demo_url(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https":
        raise RuntimeError(f"Demo source URL must use https: {url}")
    if host != ALLOWED_DEMO_HOST and not host.endswith(f".{ALLOWED_DEMO_HOST}"):
        raise RuntimeError(f"Unexpected demo source host: {host or '<missing>'}")
    return url


def fetch_text(url: str) -> str:
    url = validate_demo_url(url)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        # validate_demo_url restricts this to HTTPS OpenGameArt URLs.
        with urllib.request.urlopen(request, timeout=30) as response:  # nosec B310
            return response.read().decode("utf-8", errors="replace")
    except urllib.error.URLError:
        curl = shutil.which("curl")
        if not curl:
            raise
        result = subprocess.run(
            [curl, "-sS", "-L", "--fail", "-A", USER_AGENT, url],
            check=True,
            capture_output=True,
        )
        return result.stdout.decode("utf-8", errors="replace")


def download_file(url: str, output: Path) -> None:
    url = validate_demo_url(url)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        # validate_demo_url restricts this to HTTPS OpenGameArt URLs.
        with urllib.request.urlopen(request, timeout=60) as response:  # nosec B310
            output.write_bytes(response.read())
    except urllib.error.URLError:
        curl = shutil.which("curl")
        if not curl:
            raise
        subprocess.run(
            [curl, "-sS", "-L", "--fail", "-A", USER_AGENT, "-o", str(output), url],
            check=True,
        )


def resolve_attachment_url(source: DemoSource) -> str:
    parser = AttachmentLinkParser(source.filename)
    parser.feed(fetch_text(source.page_url))
    if not parser.match:
        raise RuntimeError(f"Could not find {source.filename!r} on {source.page_url}")
    return validate_demo_url(urljoin(source.page_url, parser.match))


def clip_to_wav(ffmpeg: str, source: Path, output: Path, start_seconds: float) -> None:
    command = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{start_seconds:.3f}",
        "-i",
        str(source),
        "-t",
        f"{CLIP_SECONDS:.3f}",
        "-vn",
        "-ar",
        str(FRAME_RATE),
        "-ac",
        str(CHANNELS),
        str(output),
    ]
    subprocess.run(command, check=True)


def prepare_sources(temp_dir: Path) -> tuple[Path, Path]:
    ffmpeg = require_ffmpeg()

    clips: list[Path] = []
    for index, source in enumerate(SOURCES, start=1):
        attachment_url = resolve_attachment_url(source)
        downloaded = temp_dir / f"source-{index}{Path(source.filename).suffix}"
        clipped = temp_dir / f"source-{index}.wav"
        download_file(attachment_url, downloaded)
        clip_to_wav(ffmpeg, downloaded, clipped, source.start_seconds)
        clips.append(clipped)

    return clips[0], clips[1]


def make_tracks(first: Path, second: Path) -> tuple[AudioTrack, AudioTrack]:
    current = AudioTrack.from_source(
        str(first),
        title=f"{SOURCES[0].title} excerpt",
        webpage=SOURCES[0].page_url,
        duration=CLIP_SECONDS,
        license="CC0",
        artist=SOURCES[0].author,
    )
    next_track = AudioTrack.from_source(
        str(second),
        title=f"{SOURCES[1].title} excerpt",
        webpage=SOURCES[1].page_url,
        duration=CLIP_SECONDS,
        license="CC0",
        artist=SOURCES[1].author,
    )
    current.crossfade_seconds = CROSSFADE_SECONDS
    return current, next_track


def render_queue_transition(first: Path, second: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    current, next_track = make_tracks(first, second)

    player = QueuePlayer(volume=0.80, crossfade_seconds=CROSSFADE_SECONDS)
    player.enqueue(current)
    player.enqueue(next_track)

    max_frames = int(OUTPUT_SECONDS_LIMIT / FRAME_DURATION)
    with wave.open(str(output), "wb") as handle:
        handle.setnchannels(CHANNELS)
        handle.setsampwidth(SAMPLE_WIDTH)
        handle.setframerate(FRAME_RATE)
        for _ in range(max_frames):
            frame = player.read_frame()
            if not frame:
                break
            handle.writeframesraw(frame)
    player.stop()


def render_lossless_demo(first: Path, second: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    current, next_track = make_tracks(first, second)
    render_lossless_transition(
        current,
        next_track,
        output,
        LosslessTransitionConfig(
            crossfade_seconds=CROSSFADE_SECONDS,
            sample_rate=FRAME_RATE,
            channels=CHANNELS,
            curve="qsin",
        ),
        timeout=60,
    )


def render_transition(
    output: Path,
    lossless_output: Path | None = DEFAULT_LOSSLESS_OUTPUT,
    lossless_flac_output: Path | None = DEFAULT_LOSSLESS_FLAC_OUTPUT,
) -> None:
    with tempfile.TemporaryDirectory() as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        first, second = prepare_sources(temp_dir)
        render_queue_transition(first, second, output)
        if lossless_output is not None:
            render_lossless_demo(first, second, lossless_output)
        if lossless_flac_output is not None:
            render_lossless_demo(first, second, lossless_flac_output)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render the Veloura public CC0 music transition demo.")
    parser.add_argument(
        "output",
        nargs="?",
        type=Path,
        default=DEFAULT_QUEUE_OUTPUT,
        help="Output WAV path for the queue-player demo.",
    )
    parser.add_argument(
        "--lossless-output",
        type=Path,
        default=DEFAULT_LOSSLESS_OUTPUT,
        help="Output WAV path for the lossless-renderer demo.",
    )
    parser.add_argument(
        "--lossless-flac-output",
        type=Path,
        default=DEFAULT_LOSSLESS_FLAC_OUTPUT,
        help="Output FLAC path for the lossless-renderer demo.",
    )
    parser.add_argument(
        "--skip-lossless",
        action="store_true",
        help="Only render the queue-player demo.",
    )
    parser.add_argument("--print-sources", action="store_true", help="Print source credits and exit.")
    args = parser.parse_args(argv)

    if args.print_sources:
        for source in SOURCES:
            print(f"{source.title} by {source.author} - CC0 - {source.page_url}")
        return 0

    lossless_output = None if args.skip_lossless else args.lossless_output
    lossless_flac_output = None if args.skip_lossless else args.lossless_flac_output
    render_transition(args.output, lossless_output, lossless_flac_output)
    print(args.output)
    if lossless_output is not None:
        print(lossless_output)
    if lossless_flac_output is not None:
        print(lossless_flac_output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
