import asyncio
import math
import struct
import tempfile
import unittest
from collections import deque
from pathlib import Path

from veloura.audio import (
    CrossfadeAudioSource,
    CrossfadeSession,
    MixerTrack,
    PCMQueuePlayer,
    SmartTransitionConfig,
    normalize_transition_config,
    planned_crossfade_seconds,
    prepare_smart_transition,
)
from veloura.audio.ffmpeg_binary import resolve_ffmpeg, require_ffmpeg
from veloura.audio.ffmpeg_stream import atempo_filter_chain, build_ffmpeg_pcm_command, should_use_reconnect


def run(coro):
    return asyncio.run(coro)


def song(title):
    return {
        "title": title,
        "webpage": f"https://example.test/{title}",
        "duration": 180,
        "requester_id": 42,
    }


def song_key(item):
    return item["title"]


def pack_samples(*samples: int) -> bytes:
    return struct.pack("<" + "h" * len(samples), *samples)


def unpack_samples(frame: bytes) -> tuple[int, ...]:
    return struct.unpack("<" + "h" * (len(frame) // 2), frame)


async def fake_resolver(item):
    return MixerTrack(
        title=item["title"],
        stream_url=f"https://stream.example.test/{item['title']}",
        webpage=item["webpage"],
        duration=item["duration"],
        requester_id=item["requester_id"],
        payload=item,
    )


class CrossfadeSessionTests(unittest.TestCase):
    def test_session_prefetches_unique_tracks(self):
        first = song("first")
        second = song("second")
        queue = deque([first, second, first])
        session = CrossfadeSession(volume=0.5, crossfade_seconds=15)

        run(
            session.ensure_buffer(
                queue,
                resolve_song=fake_resolver,
                song_key=song_key,
                quality="high",
            )
        )

        self.assertEqual(session.source.snapshot()["queue"], ["first", "second"])
        self.assertEqual(len(session.enqueued_ids), 2)
        session.stop()

    def test_dj_quality_keeps_only_next_track_buffered(self):
        first = song("first")
        second = song("second")
        queue = deque([first, second])
        session = CrossfadeSession(volume=0.5, crossfade_seconds=15)

        run(
            session.ensure_buffer(
                queue,
                resolve_song=fake_resolver,
                song_key=song_key,
                quality="dj",
            )
        )

        self.assertEqual(session.source.snapshot()["queue"], ["first"])
        self.assertEqual(len(session.enqueued_ids), 1)
        session.stop()

    def test_session_syncs_current_song_to_bot_state(self):
        current = song("current")
        next_song = song("next")
        queue = deque([next_song])
        history = deque(maxlen=20)
        skip_votes = {123}
        session = CrossfadeSession(volume=0.5, crossfade_seconds=15)
        session.source.current = MixerTrack(
            title="next",
            stream_url="https://stream.example.test/next",
            webpage=next_song["webpage"],
            duration=next_song["duration"],
            requester_id=next_song["requester_id"],
            payload=next_song,
        )

        advance = session.sync_current(
            queue=queue,
            current=current,
            history=history,
            skip_history=False,
            skip_votes=skip_votes,
            song_key=song_key,
        )

        self.assertTrue(advance.changed)
        self.assertIs(advance.song, next_song)
        self.assertEqual(list(queue), [])
        self.assertEqual(list(history), [current])
        self.assertEqual(skip_votes, set())
        session.stop()

    def test_smart_transition_uses_playable_duration(self):
        track = MixerTrack(
            title="studio track",
            stream_url="https://stream.example.test/song",
            webpage="https://example.test/song",
            duration=120,
            requester_id=42,
            trim_start=2,
            trim_end=4,
        )

        self.assertEqual(track.playable_duration, 114)

    def test_tempo_ratio_changes_effective_playable_duration(self):
        track = MixerTrack(
            title="tempo track",
            stream_url="https://stream.example.test/song",
            webpage="https://example.test/song",
            duration=120,
            requester_id=42,
            trim_start=10,
            trim_end=10,
            tempo=1.25,
        )

        self.assertEqual(track.playable_duration, 100)
        self.assertEqual(track.effective_playable_duration, 80)

    def test_atempo_filter_ignores_near_normal_speed(self):
        self.assertEqual(atempo_filter_chain(1.0), "")
        self.assertEqual(atempo_filter_chain(1.004), "")
        self.assertEqual(atempo_filter_chain(1.08), "atempo=1.08")

    def test_ffmpeg_reconnect_flags_are_url_only(self):
        local = MixerTrack("local", "/music/song.wav", "web", 180, 42)
        remote = MixerTrack("remote", "https://cdn.example.test/song", "web", 180, 42)

        self.assertFalse(should_use_reconnect(local.stream_url))
        self.assertTrue(should_use_reconnect(remote.stream_url))
        self.assertNotIn("-reconnect", build_ffmpeg_pcm_command("ffmpeg", local))
        self.assertIn("-reconnect", build_ffmpeg_pcm_command("ffmpeg", remote))

    def test_ffmpeg_resolver_finds_runtime_binary(self):
        self.assertTrue(resolve_ffmpeg())
        self.assertEqual(require_ffmpeg(), resolve_ffmpeg())

    def test_smart_transition_adapts_short_tracks(self):
        config = SmartTransitionConfig(
            enabled=True,
            base_crossfade_seconds=15,
            max_crossfade_seconds=15,
            analyze_silence=False,
            normalize_loudness=False,
        )
        track = MixerTrack(
            title="short track",
            stream_url="https://stream.example.test/short",
            webpage="https://example.test/short",
            duration=70,
            requester_id=42,
        )

        prepare_smart_transition(track, config)

        self.assertEqual(track.crossfade_seconds, planned_crossfade_seconds(track, config))
        self.assertLessEqual(track.crossfade_seconds, 4)

    def test_crossfade_uses_equal_power_curve(self):
        source = CrossfadeAudioSource(volume=1.0, crossfade_seconds=10)
        source.current = MixerTrack("current", "stream", "web", 180, 42)
        source.next_track = MixerTrack("next", "stream", "web", 180, 42)

        mixed = source._mix(pack_samples(1000, 1000), pack_samples(1000, 1000), 0.5)
        expected = round(1000 * math.sqrt(0.5) + 1000 * math.sqrt(0.5))

        self.assertEqual(unpack_samples(mixed), (expected, expected))

    def test_smart_transition_limits_live_tracks(self):
        config = SmartTransitionConfig(
            enabled=True,
            base_crossfade_seconds=15,
            max_crossfade_seconds=15,
            analyze_silence=False,
            normalize_loudness=False,
        )
        track = MixerTrack(
            title="Artist - Song Live at Somewhere",
            stream_url="https://stream.example.test/live",
            webpage="https://example.test/live",
            duration=240,
            requester_id=42,
        )

        prepare_smart_transition(track, config)

        self.assertLessEqual(track.crossfade_seconds, 3)

    def test_smart_transition_applies_cached_analysis(self):
        config = SmartTransitionConfig(
            enabled=True,
            base_crossfade_seconds=10,
            max_crossfade_seconds=10,
            analyze_silence=True,
            normalize_loudness=True,
        )
        track = MixerTrack(
            title="cached track",
            stream_url="https://stream.example.test/cached",
            webpage="https://example.test/cached",
            duration=180,
            requester_id=42,
        )

        prepare_smart_transition(
            track,
            config,
            {
                "version": 1,
                "trim_start": 1.25,
                "trim_end": 2.5,
                "gain": 1.18,
            },
        )

        self.assertEqual(track.trim_start, 1.25)
        self.assertEqual(track.trim_end, 2.5)
        self.assertEqual(track.gain, 1.18)
        self.assertTrue(track.analysis["cached"])
        self.assertEqual(track.crossfade_seconds, planned_crossfade_seconds(track, config))

    def test_corrupt_cached_analysis_is_ignored(self):
        config = SmartTransitionConfig(
            enabled=True,
            base_crossfade_seconds=10,
            analyze_silence=False,
            normalize_loudness=False,
        )
        track = MixerTrack(
            title="corrupt cache",
            stream_url="https://stream.example.test/corrupt",
            webpage="https://example.test/corrupt",
            duration=180,
            requester_id=42,
        )

        prepare_smart_transition(track, config, {"version": 1, "trim_start": "bad"})

        self.assertFalse(track.analysis.get("cached", False))
        self.assertEqual(track.trim_start, 0.0)
        self.assertEqual(track.crossfade_seconds, planned_crossfade_seconds(track, config))

    def test_transition_config_normalizes_bad_bounds(self):
        config = normalize_transition_config(
            SmartTransitionConfig(
                base_crossfade_seconds=99,
                min_crossfade_seconds=20,
                max_crossfade_seconds=4,
                silence_threshold_db=-200,
                analysis_timeout_seconds=0.01,
                loudness_min_gain=1.6,
                loudness_max_gain=0.2,
            )
        )

        self.assertEqual(config.max_crossfade_seconds, 4)
        self.assertEqual(config.min_crossfade_seconds, 4)
        self.assertEqual(config.base_crossfade_seconds, 4)
        self.assertEqual(config.silence_threshold_db, -90)
        self.assertEqual(config.analysis_timeout_seconds, 0.5)
        self.assertEqual(config.loudness_min_gain, 1.6)
        self.assertEqual(config.loudness_max_gain, 1.6)

    def test_short_track_crossfade_is_bounded_below_one_second(self):
        config = SmartTransitionConfig(
            enabled=True,
            base_crossfade_seconds=8,
            max_crossfade_seconds=12,
            analyze_silence=False,
            normalize_loudness=False,
        )
        track = MixerTrack(
            title="short clip",
            stream_url="https://stream.example.test/short",
            webpage="https://example.test/short",
            duration=0.6,
            requester_id=42,
        )

        prepare_smart_transition(track, config)

        self.assertLess(track.crossfade_seconds, 1.0)
        self.assertAlmostEqual(track.crossfade_seconds, 0.2)

    @unittest.skipUnless(resolve_ffmpeg(), "ffmpeg is required for playback failure reporting")
    def test_missing_file_sets_snapshot_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            player = PCMQueuePlayer()
            missing = Path(temp_dir) / "veloura-definitely-missing.wav"
            player.enqueue(MixerTrack("Missing", str(missing), str(missing), 10, 42))

            for _ in range(4):
                if not player.read_frame():
                    break

            snapshot = player.snapshot()
            player.stop()
            self.assertIn("Missing", snapshot.error)
            self.assertTrue(snapshot.error)

    def test_session_retries_failed_resolution(self):
        song = {"title": "retry"}
        attempts = 0

        async def flaky_resolver(_song):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("temporary")
            return MixerTrack("retry", "stream", "web", 10, 42)

        session = CrossfadeSession(volume=0.5, crossfade_seconds=5)
        queue_items = deque([song])
        run(session.ensure_buffer(queue_items, resolve_song=flaky_resolver, song_key=lambda item: item["title"]))
        run(session.ensure_buffer(queue_items, resolve_song=flaky_resolver, song_key=lambda item: item["title"]))

        self.assertEqual(attempts, 2)
        self.assertEqual(session.source.snapshot()["queue"], ["retry"])
        session.stop()


if __name__ == "__main__":
    unittest.main()
