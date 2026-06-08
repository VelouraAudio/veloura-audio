import math
import struct
import tempfile
import unittest
import wave
from pathlib import Path

from veloura.audio import AudioTrack, FileAnalysisCache, SmartTransitionConfig, prepare_smart_transition
from veloura.audio.ffmpeg_binary import resolve_ffmpeg


def write_sine_with_silence(path: Path, *, sample_rate: int = 16_000):
    sections = [
        ("silence", 0.65, 0.0),
        ("tone", 1.10, 0.35),
        ("silence", 0.55, 0.0),
    ]
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        for _, seconds, amplitude in sections:
            frames = int(sample_rate * seconds)
            for index in range(frames):
                value = 0
                if amplitude:
                    value = round(32767 * amplitude * math.sin(2 * math.pi * 440 * index / sample_rate))
                handle.writeframesraw(struct.pack("<h", value))
    return sum(seconds for _, seconds, _ in sections)


class FileAnalysisCacheTests(unittest.TestCase):
    def test_prepare_transition_reuses_cached_analysis(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = FileAnalysisCache(temp_dir)
            config = SmartTransitionConfig(
                analyze_silence=False,
                normalize_loudness=False,
                base_crossfade_seconds=8,
            )
            first = AudioTrack.from_source("https://example.test/song", title="Song", duration=180)
            second = AudioTrack.from_source("https://example.test/song", title="Song", duration=180)

            cache.prepare_transition(first, config)
            cache.prepare_transition(second, config)

            self.assertFalse(first.analysis.get("cached", False))
            self.assertTrue(second.analysis["cached"])
            self.assertEqual(second.crossfade_seconds, first.crossfade_seconds)

    def test_cache_key_changes_when_duration_changes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = FileAnalysisCache(temp_dir)
            config = SmartTransitionConfig(analyze_silence=False, normalize_loudness=False)
            short = AudioTrack.from_source("https://example.test/song", title="Song", duration=90)
            long = AudioTrack.from_source("https://example.test/song", title="Song", duration=180)

            cache.prepare_transition(short, config)
            cache.prepare_transition(long, config)

            self.assertFalse(long.analysis.get("cached", False))


@unittest.skipUnless(resolve_ffmpeg(), "ffmpeg is required for generated audio analysis")
class GeneratedAudioAnalysisTests(unittest.TestCase):
    def test_generated_wav_detects_silence_and_loudness(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "tone.wav"
            duration = write_sine_with_silence(source)
            track = AudioTrack.from_source(str(source), title="Generated Tone", duration=duration)
            config = SmartTransitionConfig(
                base_crossfade_seconds=5,
                analyze_silence=True,
                analyze_trailing_silence=True,
                silence_threshold_db=-40,
                silence_duration_seconds=0.2,
                analysis_window_seconds=4,
                analysis_timeout_seconds=5,
                max_intro_trim_seconds=2,
                max_outro_trim_seconds=2,
                normalize_loudness=True,
                loudness_analysis_seconds=2,
            )

            prepare_smart_transition(track, config)

            self.assertGreater(track.trim_start, 0.35)
            self.assertGreater(track.trim_end, 0.25)
            self.assertTrue(track.analysis["silence_analyzed"])
            self.assertTrue(track.analysis["loudness_analyzed"])
            self.assertGreater(track.gain, 0)

    def test_generated_wav_analysis_is_cached(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "cached.wav"
            duration = write_sine_with_silence(source)
            cache = FileAnalysisCache(Path(temp_dir) / "cache")
            config = SmartTransitionConfig(
                analyze_silence=True,
                analyze_trailing_silence=True,
                analysis_window_seconds=4,
                analysis_timeout_seconds=5,
                normalize_loudness=True,
                loudness_analysis_seconds=2,
            )
            first = AudioTrack.from_source(str(source), title="Cached Tone", duration=duration)
            second = AudioTrack.from_source(str(source), title="Cached Tone", duration=duration)

            cache.prepare_transition(first, config)
            cache.prepare_transition(second, config)

            self.assertFalse(first.analysis.get("cached", False))
            self.assertTrue(second.analysis["cached"])
            self.assertEqual(second.trim_start, first.trim_start)
            self.assertEqual(second.trim_end, first.trim_end)


if __name__ == "__main__":
    unittest.main()
