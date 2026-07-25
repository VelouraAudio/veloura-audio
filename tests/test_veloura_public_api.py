import asyncio
import io
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from contextlib import redirect_stderr, redirect_stdout

from veloura.audio import (
    AudioTrack,
    MIXER_CROSSFADE_SECONDS,
    MixerTrack,
    STREAMER_SAFE,
    preset_names,
    transition_preset,
)
from veloura.audio.resolver import _run_json_worker, require_yt_dlp, validate_query_scheme
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
            artist="Veloura Artist",
            album="Night Queue",
            mood="warmup",
        )

        self.assertEqual(track.title, "Local Song")
        self.assertEqual(track.webpage, "file:///music/song.wav")
        self.assertEqual(track.artist, "Veloura Artist")
        self.assertEqual(track.album, "Night Queue")
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

    def test_stream_resolver_rejects_unsupported_url_schemes(self):
        with self.assertRaises(ValueError):
            validate_query_scheme("file:///etc/passwd", ("http", "https"))

        validate_query_scheme("artist: song title", ("http", "https"))
        validate_query_scheme("https://example.test/song", ("http", "https"))

    def test_resolver_worker_protocol_returns_metadata(self):
        script = (
            "import json,sys;"
            "request=json.load(sys.stdin);"
            "json.dump({'ok':True,'info':{'url':request['query']}},sys.stdout)"
        )
        response = asyncio.run(
            _run_json_worker(
                (sys.executable, "-c", script),
                {"query": "https://example.test/audio"},
                timeout=2.0,
            )
        )

        self.assertEqual(response["url"], "https://example.test/audio")

    def test_resolver_worker_timeout_terminates_process(self):
        started = time.monotonic()
        with self.assertRaises(TimeoutError) as raised:
            asyncio.run(
                _run_json_worker(
                    (sys.executable, "-c", "import time; time.sleep(30)"),
                    {"query": "anything"},
                    timeout=0.05,
                )
            )

        self.assertLess(time.monotonic() - started, 3.0)
        self.assertIn("stream resolution exceeded", str(raised.exception))

    def test_resolver_worker_cancellation_terminates_process(self):
        async def cancel_worker():
            task = asyncio.create_task(
                _run_json_worker(
                    (sys.executable, "-c", "import time; time.sleep(30)"),
                    {"query": "anything"},
                    timeout=30.0,
                )
            )
            await asyncio.sleep(0.05)
            task.cancel()
            await task

        started = time.monotonic()
        with self.assertRaises(asyncio.CancelledError):
            asyncio.run(cancel_worker())

        self.assertLess(time.monotonic() - started, 3.0)

    def test_resolver_worker_rejects_non_json_options(self):
        with self.assertRaises(ValueError) as raised:
            asyncio.run(
                _run_json_worker(
                    (sys.executable, "-c", ""),
                    {"options": {"logger": object()}},
                    timeout=1.0,
                )
            )

        self.assertIn("JSON-compatible", str(raised.exception))

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

    def test_cli_reports_value_errors_without_traceback(self):
        error = io.StringIO()
        with redirect_stderr(error):
            code = main(["prepare", "song.wav", "--preset", "not-real"])

        self.assertEqual(code, 1)
        self.assertIn("Unknown Veloura preset", error.getvalue())
        self.assertNotIn("Traceback", error.getvalue())

    def test_doctor_rejects_bad_configured_ffmpeg(self):
        original = os.environ.get("VELOURA_FFMPEG")
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as temp_dir:
            os.environ["VELOURA_FFMPEG"] = str(Path(temp_dir) / "veloura-not-a-real-ffmpeg")
            try:
                with redirect_stdout(output):
                    code = main(["doctor"])
            finally:
                if original is None:
                    os.environ.pop("VELOURA_FFMPEG", None)
                else:
                    os.environ["VELOURA_FFMPEG"] = original

        self.assertEqual(code, 1)
        self.assertIn('"ffmpeg_usable": false', output.getvalue())


if __name__ == "__main__":
    unittest.main()
