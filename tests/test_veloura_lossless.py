import math
import struct
import tempfile
import unittest
import wave
from pathlib import Path

from veloura.audio import AudioTrack
from veloura.audio.ffmpeg_binary import resolve_ffmpeg
from veloura.audio.lossless import (
    LosslessTransitionConfig,
    build_lossless_transition_command,
    codec_args_for_output,
    render_lossless_transition,
)


def write_tone(path: Path, *, frequency: float, seconds: float = 0.55, sample_rate: int = 48_000):
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        for index in range(int(seconds * sample_rate)):
            value = round(16000 * math.sin(2 * math.pi * frequency * index / sample_rate))
            handle.writeframesraw(struct.pack("<hh", value, value))


class LosslessTransitionTests(unittest.TestCase):
    def test_codec_args_follow_output_extension(self):
        self.assertEqual(codec_args_for_output("out.flac")[:2], ["-c:a", "flac"])
        self.assertEqual(codec_args_for_output("out.wav"), ["-c:a", "pcm_f32le"])
        self.assertEqual(codec_args_for_output("out.m4a"), ["-c:a", "alac"])
        self.assertEqual(codec_args_for_output("out.aiff"), ["-c:a", "pcm_s24be"])
        with self.assertRaises(ValueError):
            codec_args_for_output("out.mp3")

    def test_build_command_uses_float_graph_and_lossless_codec(self):
        current = AudioTrack.from_source("current.flac", title="Current", duration=180)
        current.trim_start = 1.5
        current.trim_end = 2.0
        next_track = AudioTrack.from_source("next.flac", title="Next", duration=200)
        command = build_lossless_transition_command(
            "ffmpeg",
            current,
            next_track,
            "transition.flac",
            LosslessTransitionConfig(crossfade_seconds=7.5, sample_rate=96_000, curve="qsin"),
        )
        joined = " ".join(command)
        self.assertIn("aformat=sample_fmts=fltp", joined)
        self.assertIn("aresample=96000", joined)
        self.assertIn("acrossfade=d=7.500000:c1=qsin:c2=qsin", joined)
        self.assertIn("atrim=start=1.500000:end=178.000000", joined)
        self.assertIn("-compression_level", command)

    def test_invalid_config_is_rejected(self):
        with self.assertRaises(ValueError):
            build_lossless_transition_command("ffmpeg", "a.wav", "b.wav", "out.flac", LosslessTransitionConfig(channels=6))
        with self.assertRaises(ValueError):
            build_lossless_transition_command("ffmpeg", "a.wav", "b.wav", "out.flac", LosslessTransitionConfig(curve="bad;curve"))

    @unittest.skipUnless(resolve_ffmpeg(), "ffmpeg is required for render integration")
    def test_render_lossless_transition_wav(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            first = temp / "first.wav"
            second = temp / "second.wav"
            output = temp / "transition.wav"
            write_tone(first, frequency=220)
            write_tone(second, frequency=330)

            rendered = render_lossless_transition(
                first,
                second,
                output,
                LosslessTransitionConfig(crossfade_seconds=0.15, limiter=False),
                timeout=10,
            )

            self.assertEqual(rendered, output)
            self.assertTrue(output.exists())
            self.assertGreater(output.stat().st_size, 1024)


if __name__ == "__main__":
    unittest.main()
