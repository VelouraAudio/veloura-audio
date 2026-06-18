import unittest

from veloura.audio import AudioTrack, BeatProfile, PCMQueuePlayer, transition_preset


def profile(source: str, *, bpm: float, cue_in: float, cue_out: float) -> BeatProfile:
    return BeatProfile(
        source=source,
        bpm=bpm,
        confidence=0.8,
        beat_times=(cue_in, cue_out),
        cue_in=cue_in,
        cue_out=cue_out,
        analyzed_seconds=max(cue_in, cue_out, 1.0),
        reason="ok",
    )


class PCMQueuePlayerTests(unittest.TestCase):
    def test_player_exposes_typed_snapshot(self):
        player = PCMQueuePlayer(volume=0.5, crossfade_seconds=7)
        track = AudioTrack.from_source("song-a.mp3", title="Song A", duration=180)

        player.enqueue(track)
        snapshot = player.snapshot()

        self.assertIsNone(snapshot.current)
        self.assertEqual(snapshot.queue, ("Song A",))
        self.assertEqual(snapshot.volume, 0.5)
        self.assertEqual(snapshot.to_dict()["queue"], ["Song A"])
        player.stop()

    def test_player_extends_and_clears_queue(self):
        player = PCMQueuePlayer(volume=0.5, crossfade_seconds=7)
        tracks = [
            AudioTrack.from_source("song-a.mp3", title="Song A", duration=180),
            AudioTrack.from_source("song-b.mp3", title="Song B", duration=180),
        ]

        player.extend(tracks)
        self.assertEqual(tuple(track.title for track in player.queued_tracks()), ("Song A", "Song B"))

        player.clear()
        self.assertEqual(player.queued_tracks(), ())
        player.stop()

    def test_player_can_cap_queue_size(self):
        player = PCMQueuePlayer(volume=0.5, crossfade_seconds=7, max_queue_size=1)

        player.enqueue(AudioTrack.from_source("song-a.mp3", title="Song A", duration=180))
        with self.assertRaises(OverflowError):
            player.enqueue(AudioTrack.from_source("song-b.mp3", title="Song B", duration=180))

        self.assertEqual(player.snapshot().queue, ("Song A",))
        player.stop()

    def test_player_can_prepare_current_next_automix_pair(self):
        player = PCMQueuePlayer(volume=0.5, crossfade_seconds=12)
        current = AudioTrack.from_source("song-a.mp3", title="Song A", duration=180)
        next_track = AudioTrack.from_source("song-b.mp3", title="Song B", duration=190)
        player.source.current = current
        player.enqueue(next_track)

        plan = player.prepare_next_transition_pair(
            transition_preset("automix"),
            current_profile=profile("current", bpm=120, cue_in=1.0, cue_out=170.0),
            next_profile=profile("next", bpm=122, cue_in=4.0, cue_out=24.0),
        )

        self.assertIsNotNone(plan)
        self.assertEqual(current.analysis["automix"]["reason"], plan.reason)
        self.assertEqual(player.next_track().trim_start, 4.0)
        player.stop()

    def test_player_pair_helper_returns_none_without_current_track(self):
        player = PCMQueuePlayer(volume=0.5, crossfade_seconds=12)
        player.enqueue(AudioTrack.from_source("song-b.mp3", title="Song B", duration=190))

        plan = player.prepare_next_transition_pair(transition_preset("automix"), timeout=0.5)

        self.assertIsNone(plan)
        player.stop()


if __name__ == "__main__":
    unittest.main()
