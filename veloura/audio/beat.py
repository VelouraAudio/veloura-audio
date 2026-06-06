"""Beat-aware transition analysis for Veloura."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from dataclasses import asdict, dataclass
from typing import Any

from .pcm import pcm_rms

DEFAULT_SAMPLE_RATE = 11_025
DEFAULT_FRAME_SECONDS = 0.023
SAMPLE_WIDTH = 2
MIN_BEAT_CONFIDENCE = 0.18
BEAT_ANALYSIS_VERSION = 1


@dataclass(frozen=True)
class BeatProfile:
    source: str
    bpm: float
    confidence: float
    beat_times: tuple[float, ...]
    cue_in: float
    cue_out: float
    analyzed_seconds: float
    window_start: float = 0.0
    reason: str = ""


@dataclass(frozen=True)
class BeatTransitionPlan:
    crossfade_seconds: float
    current_cue_out: float
    next_cue_in: float
    bpm_delta: float
    confidence: float
    reason: str


def decode_pcm_window(
    source: str,
    *,
    start_at: float = 0.0,
    duration: float = 45.0,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    timeout: float = 12.0,
) -> bytes:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg was not found on this machine.")

    command = [
        ffmpeg,
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "error",
    ]
    if start_at > 0:
        command.extend(["-ss", f"{start_at:.3f}"])
    command.extend(
        [
            "-t",
            f"{max(1.0, duration):.3f}",
            "-i",
            source,
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(sample_rate),
            "-f",
            "s16le",
            "pipe:1",
        ]
    )
    result = subprocess.run(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0 or not result.stdout:
        error = result.stderr.decode("utf-8", "ignore").strip()
        raise RuntimeError(error or "ffmpeg did not return audio.")
    return result.stdout


def pcm_to_energy_envelope(
    pcm: bytes,
    *,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    frame_seconds: float = DEFAULT_FRAME_SECONDS,
) -> tuple[list[float], float]:
    frame_bytes = max(1, int(sample_rate * frame_seconds)) * SAMPLE_WIDTH
    values = []
    for offset in range(0, len(pcm) - frame_bytes + 1, frame_bytes):
        frame = pcm[offset : offset + frame_bytes]
        values.append(float(pcm_rms(frame, SAMPLE_WIDTH)))
    return normalize(values), frame_bytes / (sample_rate * SAMPLE_WIDTH)


def normalize(values: list[float]) -> list[float]:
    peak = max(values, default=0.0)
    if peak <= 0:
        return [0.0 for _ in values]
    return [value / peak for value in values]


def smooth(values: list[float], radius: int = 2) -> list[float]:
    if not values or radius <= 0:
        return list(values)
    result = []
    for index in range(len(values)):
        start = max(0, index - radius)
        end = min(len(values), index + radius + 1)
        result.append(sum(values[start:end]) / (end - start))
    return result


def onset_envelope(energy: list[float]) -> list[float]:
    smoothed = smooth(energy, radius=2)
    onsets = [0.0]
    for previous, current in zip(smoothed, smoothed[1:]):
        onsets.append(max(0.0, current - previous))
    return normalize(smooth(onsets, radius=1))


def estimate_bpm_from_onsets(
    onsets: list[float],
    *,
    frame_seconds: float,
    min_bpm: float = 70.0,
    max_bpm: float = 180.0,
) -> tuple[float, float]:
    if len(onsets) < 8:
        return 0.0, 0.0

    min_lag = max(1, round(60.0 / max_bpm / frame_seconds))
    max_lag = min(len(onsets) // 2, round(60.0 / min_bpm / frame_seconds))
    if max_lag <= min_lag:
        return 0.0, 0.0

    energy_floor = sum(value * value for value in onsets) / len(onsets)
    best_lag = 0
    best_score = 0.0
    scores: dict[int, float] = {}
    for lag in range(min_lag, max_lag + 1):
        score = 0.0
        count = 0
        for index in range(lag, len(onsets)):
            score += onsets[index] * onsets[index - lag]
            count += 1
        score = score / max(1, count)
        scores[lag] = score
        if score > best_score:
            best_score = score
            best_lag = lag

    if not best_lag:
        return 0.0, 0.0
    double_tempo_lag = round(best_lag / 2)
    if double_tempo_lag >= min_lag and scores.get(double_tempo_lag, 0.0) >= best_score * 0.65:
        best_lag = double_tempo_lag
        best_score = scores[best_lag]

    bpm = 60.0 / (best_lag * frame_seconds)
    confidence = best_score / (energy_floor + 1e-9)
    return bpm, max(0.0, min(1.0, confidence / 3.0))


def pick_beat_times(
    onsets: list[float],
    *,
    bpm: float,
    frame_seconds: float,
    max_beats: int = 96,
) -> tuple[float, ...]:
    if bpm <= 0 or not onsets:
        return ()
    period_frames = max(1, round(60.0 / bpm / frame_seconds))
    search_radius = max(1, round(period_frames * 0.18))
    anchor_limit = min(len(onsets), max(period_frames * 4, round(8.0 / frame_seconds)))
    anchor = max(range(anchor_limit), key=lambda index: onsets[index])

    beats = []
    index = anchor
    while index >= 0:
        beats.append(refine_peak(onsets, index, search_radius) * frame_seconds)
        index -= period_frames
    index = anchor + period_frames
    while index < len(onsets) and len(beats) < max_beats:
        beats.append(refine_peak(onsets, index, search_radius) * frame_seconds)
        index += period_frames

    unique = sorted({round(max(0.0, beat), 3) for beat in beats})
    return tuple(unique[:max_beats])


def refine_peak(values: list[float], index: int, radius: int) -> int:
    start = max(0, index - radius)
    end = min(len(values), index + radius + 1)
    return max(range(start, end), key=lambda candidate: values[candidate])


def analyze_beats_from_energy(
    energy: list[float],
    *,
    frame_seconds: float,
    source: str = "energy",
    window_start: float = 0.0,
) -> BeatProfile:
    onsets = onset_envelope(energy)
    bpm, confidence = estimate_bpm_from_onsets(onsets, frame_seconds=frame_seconds)
    relative_beat_times = pick_beat_times(onsets, bpm=bpm, frame_seconds=frame_seconds)
    beat_times = tuple(round(window_start + beat, 3) for beat in relative_beat_times)
    analyzed_seconds = len(energy) * frame_seconds
    cue_in = select_cue_in(beat_times)
    cue_out = select_cue_out(beat_times, window_start + analyzed_seconds)
    reason = "ok" if confidence >= MIN_BEAT_CONFIDENCE and beat_times else "low-confidence"
    return BeatProfile(
        source=source,
        bpm=round(bpm, 2),
        confidence=round(confidence, 3),
        beat_times=beat_times,
        cue_in=cue_in,
        cue_out=cue_out,
        analyzed_seconds=round(analyzed_seconds, 3),
        window_start=round(window_start, 3),
        reason=reason,
    )


def analyze_beats_from_pcm(
    pcm: bytes,
    *,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    frame_seconds: float = DEFAULT_FRAME_SECONDS,
    source: str = "pcm",
    window_start: float = 0.0,
) -> BeatProfile:
    energy, actual_frame_seconds = pcm_to_energy_envelope(
        pcm,
        sample_rate=sample_rate,
        frame_seconds=frame_seconds,
    )
    return analyze_beats_from_energy(
        energy,
        frame_seconds=actual_frame_seconds,
        source=source,
        window_start=window_start,
    )


def analyze_source(
    source: str,
    *,
    start_at: float = 0.0,
    duration: float = 45.0,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    timeout: float = 12.0,
) -> BeatProfile:
    pcm = decode_pcm_window(
        source,
        start_at=start_at,
        duration=duration,
        sample_rate=sample_rate,
        timeout=timeout,
    )
    return analyze_beats_from_pcm(
        pcm,
        sample_rate=sample_rate,
        source=source,
        window_start=start_at,
    )


def analyze_best_source_window(
    source: str,
    *,
    starts: list[float],
    duration: float = 30.0,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    timeout: float = 12.0,
) -> BeatProfile:
    profiles = []
    last_error: Exception | None = None
    for start_at in unique_starts(starts):
        try:
            profiles.append(
                analyze_source(
                    source,
                    start_at=start_at,
                    duration=duration,
                    sample_rate=sample_rate,
                    timeout=timeout,
                )
            )
        except Exception as e:
            last_error = e
    if not profiles:
        if last_error:
            raise last_error
        raise RuntimeError("No beat windows could be analyzed.")
    return max(profiles, key=profile_score)


def unique_starts(starts: list[float]) -> list[float]:
    values = []
    seen = set()
    for start in starts:
        value = round(max(0.0, float(start or 0.0)), 3)
        if value in seen:
            continue
        seen.add(value)
        values.append(value)
    return values


def profile_score(profile: BeatProfile) -> float:
    beat_bonus = min(0.12, len(profile.beat_times) / 400)
    bpm_bonus = 0.05 if 70 <= profile.bpm <= 180 else 0.0
    return profile.confidence + beat_bonus + bpm_bonus


def select_cue_in(beat_times: tuple[float, ...], minimum: float = 0.5) -> float:
    for beat in beat_times:
        if beat >= minimum:
            return beat
    return beat_times[0] if beat_times else 0.0


def select_cue_out(beat_times: tuple[float, ...], analyzed_seconds: float, target_before_end: float = 8.0) -> float:
    if not beat_times:
        return max(0.0, analyzed_seconds - target_before_end)
    target = max(0.0, analyzed_seconds - target_before_end)
    return min(beat_times, key=lambda beat: abs(beat - target))


def plan_beat_transition(
    current: BeatProfile,
    next_track: BeatProfile,
    *,
    base_crossfade_seconds: float = 8.0,
    max_crossfade_seconds: float = 15.0,
) -> BeatTransitionPlan:
    confidence = min(current.confidence, next_track.confidence)
    bpm_delta = abs(current.bpm - next_track.bpm) if current.bpm and next_track.bpm else 999.0

    if confidence < MIN_BEAT_CONFIDENCE:
        return BeatTransitionPlan(
            crossfade_seconds=max(3.0, min(base_crossfade_seconds, 6.0)),
            current_cue_out=current.cue_out,
            next_cue_in=next_track.cue_in,
            bpm_delta=round(bpm_delta, 2),
            confidence=round(confidence, 3),
            reason="fallback-low-confidence",
        )

    if bpm_delta <= 4:
        fade = min(max_crossfade_seconds, max(base_crossfade_seconds, 10.0))
        reason = "beat-match"
    elif bpm_delta <= 10:
        fade = min(max_crossfade_seconds, base_crossfade_seconds)
        reason = "near-tempo"
    else:
        fade = max(3.0, min(base_crossfade_seconds, 5.0))
        reason = "tempo-mismatch-short-blend"

    return BeatTransitionPlan(
        crossfade_seconds=round(fade, 2),
        current_cue_out=current.cue_out,
        next_cue_in=next_track.cue_in,
        bpm_delta=round(bpm_delta, 2),
        confidence=round(confidence, 3),
        reason=reason,
    )


def is_actionable_beat_plan(
    plan: BeatTransitionPlan,
    *,
    min_confidence: float = MIN_BEAT_CONFIDENCE,
    allow_near_tempo: bool = True,
) -> bool:
    if float(plan.confidence or 0) < min_confidence:
        return False
    reasons = {"beat-match", "bpm-sync"}
    if allow_near_tempo:
        reasons.add("near-tempo")
    return plan.reason in reasons


def synthetic_pulse_energy(
    *,
    bpm: float,
    seconds: float = 20.0,
    frame_seconds: float = DEFAULT_FRAME_SECONDS,
    pulse_width_frames: int = 2,
) -> list[float]:
    frames = int(seconds / frame_seconds)
    period = 60.0 / bpm
    values = [0.02 for _ in range(frames)]
    beat = 0.5
    while beat < seconds:
        center = round(beat / frame_seconds)
        for offset in range(-pulse_width_frames, pulse_width_frames + 1):
            index = center + offset
            if 0 <= index < frames:
                distance = abs(offset) / max(1, pulse_width_frames)
                values[index] = max(values[index], 1.0 - 0.55 * distance)
        beat += period
    return values


def profile_to_dict(profile: BeatProfile) -> dict[str, Any]:
    data = asdict(profile)
    data["version"] = BEAT_ANALYSIS_VERSION
    data["beat_times"] = list(profile.beat_times)
    data["beat_count"] = len(profile.beat_times)
    return data


def compact_profile_to_dict(profile: BeatProfile) -> dict[str, Any]:
    data = profile_to_dict(profile)
    data["beat_times"] = data["beat_times"][:16]
    return data


def profile_from_dict(data: dict[str, Any] | None) -> BeatProfile | None:
    if not data or int(data.get("version", 0) or 0) != BEAT_ANALYSIS_VERSION:
        return None
    try:
        return BeatProfile(
            source=str(data.get("source") or ""),
            bpm=float(data.get("bpm") or 0.0),
            confidence=float(data.get("confidence") or 0.0),
            beat_times=tuple(float(value) for value in data.get("beat_times", []) or []),
            cue_in=float(data.get("cue_in") or 0.0),
            cue_out=float(data.get("cue_out") or 0.0),
            analyzed_seconds=float(data.get("analyzed_seconds") or 0.0),
            window_start=float(data.get("window_start") or 0.0),
            reason=str(data.get("reason") or ""),
        )
    except (TypeError, ValueError):
        return None


def plan_to_dict(plan: BeatTransitionPlan) -> dict[str, Any]:
    return asdict(plan)


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze and plan a Veloura beat-aware transition.")
    parser.add_argument("current", help="Current audio source URL/path")
    parser.add_argument("next", help="Next audio source URL/path")
    parser.add_argument("--duration", type=float, default=45.0)
    parser.add_argument("--current-start", type=float, default=0.0)
    parser.add_argument("--next-start", type=float, default=0.0)
    args = parser.parse_args()

    current = analyze_source(args.current, start_at=args.current_start, duration=args.duration)
    next_track = analyze_source(args.next, start_at=args.next_start, duration=args.duration)
    plan = plan_beat_transition(current, next_track)
    print(
        json.dumps(
            {
                "current": compact_profile_to_dict(current),
                "next": compact_profile_to_dict(next_track),
                "plan": plan_to_dict(plan),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
