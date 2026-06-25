import unittest

from veloura.audio import (
    AudioTrack,
    BeatProfile,
    apply_automix_plan,
    current_analysis_starts,
    plan_automix_transition,
    plan_slm_transition,
    prepare_automix_transition_pair,
    tempo_ratio_for_bpm,
    transition_preset,
)


def profile(source: str, *, bpm: float, confidence: float, cue_in: float, cue_out: float) -> BeatProfile:
    return BeatProfile(
        source=source,
        bpm=bpm,
        confidence=confidence,
        beat_times=(cue_in, cue_out),
        cue_in=cue_in,
        cue_out=cue_out,
        analyzed_seconds=max(cue_out, cue_in, 1.0),
        reason="ok",
    )


class AutoMixTests(unittest.TestCase):
    def test_slm_plan_extends_confident_tempo_match(self):
        config = transition_preset("automix")
        current = AudioTrack.from_source("current.mp3", title="Current", duration=180)
        next_track = AudioTrack.from_source("next.mp3", title="Next", duration=190)

        plan = plan_slm_transition(
            current,
            next_track,
            config,
            current_profile=profile("current", bpm=124, confidence=0.8, cue_in=1.0, cue_out=170.0),
            next_profile=profile("next", bpm=126, confidence=0.75, cue_in=4.0, cue_out=22.0),
        )

        self.assertGreaterEqual(plan.crossfade_seconds, 10.0)
        self.assertEqual(plan.reason, "slm-beat-and-energy-match")
        self.assertGreater(plan.confidence, 0.8)
        self.assertLessEqual(plan.bpm_delta, 4.0)

    def test_slm_plan_shortens_tempo_mismatch(self):
        config = transition_preset("automix")
        current = AudioTrack.from_source("current.mp3", title="Current", duration=180)
        next_track = AudioTrack.from_source("next.mp3", title="Next", duration=190)

        plan = plan_slm_transition(
            current,
            next_track,
            config,
            current_profile=profile("current", bpm=90, confidence=0.8, cue_in=1.0, cue_out=170.0),
            next_profile=profile("next", bpm=133, confidence=0.8, cue_in=4.0, cue_out=22.0),
        )

        self.assertLessEqual(plan.crossfade_seconds, 5.0)
        self.assertEqual(plan.reason, "slm-tempo-mismatch-short-blend")
        self.assertGreater(plan.bpm_delta, 10.0)

    def test_slm_plan_caps_short_tracks(self):
        config = transition_preset("automix")
        current = AudioTrack.from_source("current.mp3", title="Current", duration=38)
        next_track = AudioTrack.from_source("next.mp3", title="Next", duration=180)

        plan = plan_slm_transition(
            current,
            next_track,
            config,
            current_profile=profile("current", bpm=120, confidence=0.8, cue_in=1.0, cue_out=30.0),
            next_profile=profile("next", bpm=120, confidence=0.8, cue_in=4.0, cue_out=22.0),
        )

        self.assertEqual(plan.crossfade_seconds, 2.0)
        self.assertEqual(plan.reason, "slm-short-track")
        self.assertTrue(plan.safety_capped)

    def test_automix_respects_slm_short_track_cap(self):
        config = transition_preset("automix")
        current = AudioTrack.from_source("current.mp3", title="Current", duration=38)
        next_track = AudioTrack.from_source("next.mp3", title="Next", duration=180)

        plan = plan_automix_transition(
            current,
            next_track,
            profile("current", bpm=120, confidence=0.8, cue_in=1.0, cue_out=30.0),
            profile("next", bpm=120, confidence=0.8, cue_in=4.0, cue_out=22.0),
            config,
        )

        self.assertEqual(plan.crossfade_seconds, 2.0)
        self.assertTrue(plan.slm_plan.safety_capped)

    def test_tempo_ratio_is_conservative(self):
        self.assertEqual(tempo_ratio_for_bpm(120, 120), 1.0)
        self.assertEqual(tempo_ratio_for_bpm(128, 120), 1.06)
        self.assertEqual(tempo_ratio_for_bpm(112, 120), 0.94)
        self.assertEqual(tempo_ratio_for_bpm(80, 160), 1.0)
        self.assertEqual(tempo_ratio_for_bpm(160, 80), 1.0)
        self.assertEqual(tempo_ratio_for_bpm(0, 120), 1.0)

    def test_automix_plan_uses_beat_cues_and_tempo_nudge(self):
        config = transition_preset("automix")
        current = AudioTrack.from_source("current.mp3", title="Current", duration=180)
        next_track = AudioTrack.from_source("next.mp3", title="Next", duration=190)

        plan = plan_automix_transition(
            current,
            next_track,
            profile("current", bpm=124, confidence=0.8, cue_in=1.0, cue_out=170.0),
            profile("next", bpm=126, confidence=0.75, cue_in=4.0, cue_out=22.0),
            config,
        )

        self.assertEqual(plan.reason, "automix-beat-match")
        self.assertGreaterEqual(plan.crossfade_seconds, 10)
        self.assertEqual(plan.next_trim_start, 4.0)
        self.assertAlmostEqual(plan.next_tempo, 0.9841)
        self.assertIsNotNone(plan.slm_plan)
        self.assertEqual(plan.slm_plan.reason, "slm-beat-and-energy-match")

    def test_apply_automix_plan_updates_tracks_for_crossfade_source(self):
        config = transition_preset("automix")
        current = AudioTrack.from_source("current.mp3", title="Current", duration=180)
        next_track = AudioTrack.from_source("next.mp3", title="Next", duration=190)
        plan = plan_automix_transition(
            current,
            next_track,
            profile("current", bpm=120, confidence=0.8, cue_in=1.0, cue_out=170.0),
            profile("next", bpm=120, confidence=0.8, cue_in=6.0, cue_out=24.0),
            config,
        )

        apply_automix_plan(current, next_track, plan)

        self.assertEqual(current.crossfade_seconds, plan.crossfade_seconds)
        self.assertEqual(next_track.trim_start, 6.0)
        self.assertEqual(next_track.tempo, 1.0)
        self.assertEqual(current.analysis["automix"]["version"], 1)
        self.assertEqual(next_track.analysis["automix"]["source"], "next")

    def test_automix_falls_back_when_beat_confidence_is_low(self):
        config = transition_preset("automix")
        current = AudioTrack.from_source("current.mp3", title="Current", duration=180)
        next_track = AudioTrack.from_source("next.mp3", title="Next", duration=190)

        plan = plan_automix_transition(
            current,
            next_track,
            profile("current", bpm=120, confidence=0.1, cue_in=1.0, cue_out=170.0),
            profile("next", bpm=120, confidence=0.1, cue_in=6.0, cue_out=24.0),
            config,
        )

        self.assertEqual(plan.reason, "fallback-low-confidence")
        self.assertLessEqual(plan.crossfade_seconds, 4.0)
        self.assertEqual(plan.next_trim_start, 0.0)
        self.assertEqual(plan.next_tempo, 1.0)

    def test_automix_preset_is_available(self):
        names = set(transition_preset(name).base_crossfade_seconds for name in ("automix", "auto-mix", "slm"))
        self.assertEqual(names, {9.0})

    def test_current_analysis_starts_uses_outro_window(self):
        track = AudioTrack.from_source("current.mp3", title="Current", duration=180)

        self.assertEqual(current_analysis_starts(track, 45), [135.0])

    def test_prepare_pair_can_use_supplied_profiles(self):
        config = transition_preset("automix")
        current = AudioTrack.from_source("current.mp3", title="Current", duration=180)
        next_track = AudioTrack.from_source("next.mp3", title="Next", duration=190)

        plan = prepare_automix_transition_pair(
            current,
            next_track,
            config,
            current_profile=profile("current", bpm=122, confidence=0.8, cue_in=1.0, cue_out=170.0),
            next_profile=profile("next", bpm=124, confidence=0.8, cue_in=3.0, cue_out=24.0),
        )

        self.assertEqual(current.analysis["automix"]["reason"], plan.reason)
        self.assertEqual(next_track.trim_start, 3.0)

    def test_prepare_pair_falls_back_when_analysis_fails(self):
        config = transition_preset("automix")
        current = AudioTrack.from_source("missing-current.mp3", title="Current", duration=180)
        next_track = AudioTrack.from_source("missing-next.mp3", title="Next", duration=190)

        plan = prepare_automix_transition_pair(current, next_track, config, timeout=0.5)

        self.assertEqual(plan.reason, "fallback-no-beat-profile")
        self.assertLessEqual(current.crossfade_seconds, 4.0)


if __name__ == "__main__":
    unittest.main()
