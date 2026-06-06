import unittest

from veloura.audio import (
    DEFAULT_FRAME_SECONDS,
    analyze_beats_from_energy,
    is_actionable_beat_plan,
    plan_beat_transition,
    profile_from_dict,
    profile_to_dict,
    synthetic_pulse_energy,
    unique_starts,
)


class BeatAwareExperimentTests(unittest.TestCase):
    def test_detects_synthetic_bpm(self):
        energy = synthetic_pulse_energy(bpm=120, seconds=24, frame_seconds=DEFAULT_FRAME_SECONDS)

        profile = analyze_beats_from_energy(
            energy,
            frame_seconds=DEFAULT_FRAME_SECONDS,
            source="synthetic-120",
        )

        self.assertGreaterEqual(profile.confidence, 0.25)
        self.assertAlmostEqual(profile.bpm, 120, delta=6)
        self.assertGreaterEqual(len(profile.beat_times), 16)

    def test_transition_plan_prefers_matching_bpm(self):
        current = analyze_beats_from_energy(
            synthetic_pulse_energy(bpm=124, seconds=24, frame_seconds=DEFAULT_FRAME_SECONDS),
            frame_seconds=DEFAULT_FRAME_SECONDS,
            source="current",
        )
        next_track = analyze_beats_from_energy(
            synthetic_pulse_energy(bpm=126, seconds=24, frame_seconds=DEFAULT_FRAME_SECONDS),
            frame_seconds=DEFAULT_FRAME_SECONDS,
            source="next",
        )

        plan = plan_beat_transition(current, next_track, base_crossfade_seconds=8)

        self.assertEqual(plan.reason, "beat-match")
        self.assertGreaterEqual(plan.crossfade_seconds, 10)
        self.assertTrue(is_actionable_beat_plan(plan, min_confidence=0.22))

    def test_transition_plan_shortens_mismatched_bpm(self):
        current = analyze_beats_from_energy(
            synthetic_pulse_energy(bpm=90, seconds=24, frame_seconds=DEFAULT_FRAME_SECONDS),
            frame_seconds=DEFAULT_FRAME_SECONDS,
            source="current",
        )
        next_track = analyze_beats_from_energy(
            synthetic_pulse_energy(bpm=150, seconds=24, frame_seconds=DEFAULT_FRAME_SECONDS),
            frame_seconds=DEFAULT_FRAME_SECONDS,
            source="next",
        )

        plan = plan_beat_transition(current, next_track, base_crossfade_seconds=8)

        self.assertEqual(plan.reason, "tempo-mismatch-short-blend")
        self.assertLessEqual(plan.crossfade_seconds, 5)

    def test_profile_keeps_window_start(self):
        profile = analyze_beats_from_energy(
            synthetic_pulse_energy(bpm=120, seconds=16, frame_seconds=DEFAULT_FRAME_SECONDS),
            frame_seconds=DEFAULT_FRAME_SECONDS,
            source="windowed",
            window_start=42,
        )

        self.assertEqual(profile.window_start, 42)
        self.assertGreaterEqual(profile.cue_in, 42)

    def test_unique_starts_removes_duplicates(self):
        self.assertEqual(unique_starts([0, 0.0, -2, 12.1234, 12.1235]), [0.0, 12.123])

    def test_profile_round_trip_for_cache(self):
        profile = analyze_beats_from_energy(
            synthetic_pulse_energy(bpm=118, seconds=16, frame_seconds=DEFAULT_FRAME_SECONDS),
            frame_seconds=DEFAULT_FRAME_SECONDS,
            source="cache",
        )

        restored = profile_from_dict(profile_to_dict(profile))

        self.assertIsNotNone(restored)
        self.assertEqual(restored.bpm, profile.bpm)
        self.assertEqual(restored.beat_times, profile.beat_times)


if __name__ == "__main__":
    unittest.main()
