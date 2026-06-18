"""Crossfade playback session helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Iterable

from .crossfade import CrossfadeAudioSource
from .models import MixerTrack

SongKey = Callable[[Any], str]
TrackResolver = Callable[[Any], Awaitable[MixerTrack]]
ErrorHandler = Callable[[Any, Exception], Awaitable[None] | None]

BUFFER_LIMITS = {
    "stable": 1,
    "balanced": 2,
    "high": 3,
    "dj": 1,
}


@dataclass
class CrossfadeAdvance:
    changed: bool = False
    song: Any | None = None
    previous: Any | None = None
    skip_history: bool = False


class CrossfadeSession:
    def __init__(self, *, volume: float, crossfade_seconds: float, max_queue_size: int | None = None):
        self.source = CrossfadeAudioSource(
            volume=volume,
            crossfade_seconds=crossfade_seconds,
            max_queue_size=max_queue_size,
        )
        self.enqueued_ids: set[str] = set()

    def song_id(self, song: Any, song_key: SongKey) -> str:
        return f"{id(song)}:{song_key(song)}"

    def apply_settings(self, *, volume: float, crossfade_seconds: float, enabled: bool = True):
        self.source.set_volume(volume)
        self.source.set_crossfade(crossfade_seconds if enabled else 0)

    def enqueue_initial(self, song: Any, track: MixerTrack, song_key: SongKey):
        track.payload = song
        self.source.enqueue(track)
        self.enqueued_ids.add(self.song_id(song, song_key))

    def clear_buffer(self, *, current: Any | None = None, song_key: SongKey | None = None):
        self.source.clear_pending()
        self.enqueued_ids.clear()
        if current is not None and song_key is not None:
            self.enqueued_ids.add(self.song_id(current, song_key))

    async def ensure_buffer(
        self,
        queue: Iterable[Any],
        *,
        resolve_song: TrackResolver,
        song_key: SongKey,
        quality: str = "balanced",
        on_error: ErrorHandler | None = None,
    ):
        limit = BUFFER_LIMITS.get(quality, BUFFER_LIMITS["balanced"])
        for song in list(queue):
            if len(self.source.snapshot()["queue"]) >= limit:
                return
            song_id = self.song_id(song, song_key)
            if song_id in self.enqueued_ids:
                continue
            try:
                track = await resolve_song(song)
            except Exception as e:
                if on_error:
                    result = on_error(song, e)
                    if result:
                        await result
                continue
            track.payload = song
            self.source.enqueue(track)
            self.enqueued_ids.add(song_id)

    def current_song(self):
        track = self.source.current_track_nonblocking()
        if not track:
            return None
        payload = track.payload
        return payload if payload is not None else getattr(track, "song", None)

    def is_alive(self) -> bool:
        snapshot = self.source.snapshot()
        if snapshot.get("busy"):
            return True
        return bool(snapshot.get("current") or snapshot.get("queue"))

    def sync_current(
        self,
        *,
        queue,
        current,
        history,
        skip_history: bool,
        skip_votes,
        song_key: SongKey,
    ) -> CrossfadeAdvance:
        song = self.current_song()
        if not song or current is song:
            return CrossfadeAdvance(changed=False, skip_history=skip_history)

        previous = current
        if previous and not skip_history:
            history.append(previous)

        if queue and queue[0] is song:
            queue.popleft()
        else:
            key = song_key(song)
            for queued in list(queue):
                if queued is song or song_key(queued) == key:
                    try:
                        queue.remove(queued)
                    except ValueError:
                        pass
                    break

        skip_votes.clear()
        return CrossfadeAdvance(
            changed=True,
            song=song,
            previous=previous,
            skip_history=False,
        )

    def skip(self) -> bool:
        return self.source.skip()

    def stop(self):
        self.source.stop()
        self.enqueued_ids.clear()
