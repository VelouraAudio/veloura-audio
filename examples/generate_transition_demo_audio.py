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
from urllib.parse import urljoin

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from veloura.audio import AudioTrack, FRAME_RATE, PCMQueuePlayer

CHANNELS = 2
SAMPLE_WIDTH = 2
FRAME_DURATION = 0.02
CLIP_SECONDS = 9.0
CROSSFADE_SECONDS = 4.0
OUTPUT_SECONDS_LIMIT = 16.0
USER_AGENT = "veloura-audio-demo/0.5.1"


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


def fetch_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
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
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
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
    return urljoin(source.page_url, parser.match)


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
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg was not found on this machine.")

    clips: list[Path] = []
    for index, source in enumerate(SOURCES, start=1):
        attachment_url = resolve_attachment_url(source)
        downloaded = temp_dir / f"source-{index}{Path(source.filename).suffix}"
        clipped = temp_dir / f"source-{index}.wav"
        download_file(attachment_url, downloaded)
        clip_to_wav(ffmpeg, downloaded, clipped, source.start_seconds)
        clips.append(clipped)

    return clips[0], clips[1]


def render_transition(output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        first, second = prepare_sources(temp_dir)

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

        player = PCMQueuePlayer(volume=0.80, crossfade_seconds=CROSSFADE_SECONDS)
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render the Veloura public CC0 music transition demo.")
    parser.add_argument(
        "output",
        nargs="?",
        type=Path,
        default=PROJECT_ROOT / "docs" / "assets" / "veloura-transition-demo.wav",
        help="Output WAV path.",
    )
    parser.add_argument("--print-sources", action="store_true", help="Print source credits and exit.")
    args = parser.parse_args(argv)

    if args.print_sources:
        for source in SOURCES:
            print(f"{source.title} by {source.author} - CC0 - {source.page_url}")
        return 0

    render_transition(args.output)
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
