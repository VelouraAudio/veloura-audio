"""Shared audio engine constants."""

import os

FRAME_RATE = 48_000
CHANNELS = 2
SAMPLE_WIDTH = 2
FRAME_DURATION = 0.02
FRAME_BYTES = int(FRAME_RATE * FRAME_DURATION * CHANNELS * SAMPLE_WIDTH)

MIXER_DEFAULT_VOLUME = max(0.0, min(1.5, float(os.getenv("MIXER_DEFAULT_VOLUME", "0.65"))))
MIXER_CROSSFADE_SECONDS = max(0.0, min(15.0, float(os.getenv("MIXER_CROSSFADE_SECONDS", "5"))))

YDL_STREAM_OPTIONS = {
    "format": "bestaudio[abr>=128]/bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch",
    "source_address": "0.0.0.0",
    "format_sort": ["abr", "asr", "codec:opus"],
    "prefer_free_formats": True,
}
