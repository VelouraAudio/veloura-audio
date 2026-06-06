import io
import unittest
from contextlib import redirect_stderr, redirect_stdout

from veloura.audio import (
    AudioTrack,
    MIXER_CROSSFADE_SECONDS,
    MixerTrack,
    STREAMER_SAFE,
    preset_names,
    transition_preset,
)
from veloura.audio.resolver import require_yt_dlp
from veloura.cli import main
import veloura.cli as cli_module


class VelouraPublicApiTests(unittest.TestCase):
    def test_audio_track_keeps_mixer_track_compatibility(self):
        track = MixerTrack("Song", "https://stream.example.test/song")

        self.assertIsInstance(track, AudioTrack)
        self.assertEqual(track.requester_id, 0)
        self.assertEqual(track.stable_id, "https://stream.example.test/song")

    def test_audio_track_from_source_is_project_agnostic(self):
        track = AudioTrack.from_source(
            "file:///music/song.wav",
            title="Local Song",
            duration=120,
            mood="warmup",
        )

        self.assertEqual(track.title, "Local Song")
        self.assertEqual(track.webpage, "file:///music/song.wav")
        self.assertEqual(track.metadata["mood"], "warmup")
        self.assertEqual(track.playable_duration, 120)

    def test_streamer_preset_is_normalized(self):
        config = transition_preset("streamer")

        self.assertEqual(config, STREAMER_SAFE)
        self.assertGreaterEqual(config.base_crossfade_seconds, MIXER_CROSSFADE_SECONDS)
        self.assertTrue(config.analyze_silence)
        self.assertTrue(config.normalize_loudness)

    def test_unknown_preset_lists_available_names(self):
        with self.assertRaises(ValueError) as raised:
            transition_preset("space-radio")

        self.assertIn("streamer", str(raised.exception))

    def test_cli_lists_presets(self):
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(["presets"])

        self.assertEqual(code, 0)
        listed = set(output.getvalue().splitlines())
        self.assertTrue(set(preset_names()).issubset(listed))

    def test_stream_resolver_reports_missing_optional_dependency(self):
        try:
            require_yt_dlp()
        except RuntimeError as exc:
            self.assertIn("veloura-audio[stream]", str(exc))

    def test_cli_reports_runtime_errors_without_traceback(self):
        async def fail_resolve(_args):
            raise RuntimeError("missing optional thing")

        original = cli_module.resolve_track
        cli_module.resolve_track = fail_resolve
        error = io.StringIO()
        try:
            with redirect_stderr(error):
                code = main(["resolve", "anything"])
        finally:
            cli_module.resolve_track = original

        self.assertEqual(code, 1)
        self.assertIn("missing optional thing", error.getvalue())
        self.assertNotIn("Traceback", error.getvalue())


if __name__ == "__main__":
    unittest.main()
