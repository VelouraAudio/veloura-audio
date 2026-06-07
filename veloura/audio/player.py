"""Discord-independent PCM queue player facade."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from .automix import AutoMixPlan, prepare_automix_transition_pair
from .beat import BeatProfile
from .constants import MIXER_CROSSFADE_SECONDS, MIXER_DEFAULT_VOLUME
from .crossfade import CrossfadeAudioSource
from .models import AudioTrack
from .transition import SmartTransitionConfig


@dataclass(frozen=True)
class QueueSnapshot:
    current: str | None
    elapsed: float
    duration: float
    queue: tuple[str, ...]
    volume: float
    crossfade_seconds: float
    error: str
    busy: bool = False

    def to_dict(self) -> dict:
        data = asdict(self)
        data["queue"] = list(self.queue)
        return data


class PCMQueuePlayer:
    """Small PCM queue player for apps that are not Discord voice clients.

    The player exposes prepared PCM frames through ``read_frame``. It does not
    hide expensive analysis inside queue operations; callers can prepare tracks
    and AutoMix pairs before or beside playback.
    """

    def __init__(
        self,
        *,
        volume: float = MIXER_DEFAULT_VOLUME,
        crossfade_seconds: float = MIXER_CROSSFADE_SECONDS,
    ):
        self.source = CrossfadeAudioSource(volume=volume, crossfade_seconds=crossfade_seconds)

    def enqueue(self, track: AudioTrack) -> AudioTrack:
        self.source.enqueue(track)
        return track

    def extend(self, tracks: list[AudioTrack] | tuple[AudioTrack, ...]) -> None:
        for track in tracks:
            self.enqueue(track)

    def read_frame(self) -> bytes:
        return self.source.read()

    def read(self) -> bytes:
        return self.read_frame()

    def skip(self) -> bool:
        return self.source.skip()

    def clear(self) -> None:
        self.source.clear_pending()

    def stop(self) -> None:
        self.source.stop()

    def set_volume(self, volume: float) -> None:
        self.source.set_volume(volume)

    def set_crossfade(self, seconds: float) -> None:
        self.source.set_crossfade(seconds)

    def current_track(self) -> AudioTrack | None:
        return self.source.current_track_nonblocking()

    def queued_tracks(self) -> tuple[AudioTrack, ...]:
        return self.source.queued_tracks_nonblocking() or ()

    def next_track(self) -> AudioTrack | None:
        queued = self.queued_tracks()
        return queued[0] if queued else None

    def snapshot(self) -> QueueSnapshot:
        data = self.source.snapshot()
        return QueueSnapshot(
            current=data.get("current"),
            elapsed=float(data.get("elapsed") or 0.0),
            duration=float(data.get("duration") or 0.0),
            queue=tuple(data.get("queue") or ()),
            volume=float(data.get("volume") or 0.0),
            crossfade_seconds=float(data.get("crossfade") or 0.0),
            error=str(data.get("error") or ""),
            busy=bool(data.get("busy", False)),
        )

    def is_active(self) -> bool:
        snapshot = self.snapshot()
        return bool(snapshot.current or snapshot.queue or snapshot.busy)

    def prepare_next_transition_pair(
        self,
        config: SmartTransitionConfig,
        *,
        current_profile: BeatProfile | None = None,
        next_profile: BeatProfile | None = None,
        analysis_seconds: float = 45.0,
        timeout: float | None = None,
    ) -> AutoMixPlan | None:
        current = self.current_track()
        next_track = self.next_track()
        if not current or not next_track:
            return None
        return prepare_automix_transition_pair(
            current,
            next_track,
            config,
            current_profile=current_profile,
            next_profile=next_profile,
            analysis_seconds=analysis_seconds,
            timeout=timeout,
        )
