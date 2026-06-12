"""Discord PCM audio source with true crossfade mixing."""

import math
import threading
from collections import deque

try:
    import discord
except ImportError:  # pragma: no cover - package can be used outside Discord projects
    discord = None

from .constants import FRAME_DURATION, MIXER_CROSSFADE_SECONDS, MIXER_DEFAULT_VOLUME, SAMPLE_WIDTH
from .ffmpeg_stream import FFmpegPCMStream
from .models import MixerTrack
from .pcm import pcm_add, pcm_mul


AudioSourceBase = discord.AudioSource if discord else object


class CrossfadeAudioSource(AudioSourceBase):
    def __init__(self, *, volume: float = MIXER_DEFAULT_VOLUME, crossfade_seconds: float = MIXER_CROSSFADE_SECONDS):
        self.volume = volume
        self.crossfade_seconds = crossfade_seconds
        self.queue: deque[MixerTrack] = deque()
        self.current: MixerTrack | None = None
        self.current_stream: FFmpegPCMStream | None = None
        self.current_elapsed = 0.0
        self.next_track: MixerTrack | None = None
        self.next_stream: FFmpegPCMStream | None = None
        self.next_elapsed = 0.0
        self.stopped = False
        self.skip_requested = False
        self.clear_requested = False
        self.last_error = ""
        self.lock = threading.RLock()

    def is_opus(self) -> bool:
        return False

    def enqueue(self, track: MixerTrack):
        with self.lock:
            self.queue.append(track)

    def clear_pending(self):
        if not self.lock.acquire(blocking=False):
            self.clear_requested = True
            return
        try:
            self.queue.clear()
            self._close_next_locked()
            self.clear_requested = False
        finally:
            self.lock.release()

    def skip(self) -> bool:
        if not self.lock.acquire(blocking=False):
            self.skip_requested = True
            return True
        try:
            self._close_current_locked()
            if self._promote_next_locked():
                return True
            return self._start_next_locked()
        finally:
            self.lock.release()

    def stop(self):
        self.stopped = True
        if not self.lock.acquire(blocking=False):
            self.clear_requested = True
            return
        try:
            self.queue.clear()
            self._close_current_locked()
            self._close_next_locked()
            self.clear_requested = False
        finally:
            self.lock.release()

    def set_volume(self, volume: float):
        self.volume = max(0.0, min(1.5, volume))

    def set_crossfade(self, seconds: float):
        self.crossfade_seconds = max(0.0, min(15.0, seconds))

    def snapshot(self) -> dict:
        acquired = self.lock.acquire(blocking=False)
        try:
            queued = []
            if self.next_track:
                queued.append(self.next_track.title)
            try:
                queued.extend(track.title for track in self.queue)
            except RuntimeError:
                queued.append("updating")
            return {
                "current": self.current.title if self.current else None,
                "elapsed": self.current_elapsed,
                "duration": self._duration_locked(self.current),
                "queue": queued,
                "volume": self.volume,
                "crossfade": self._crossfade_locked(self.current),
                "error": self.last_error,
                "busy": not acquired,
            }
        finally:
            if acquired:
                self.lock.release()

    def current_track_nonblocking(self) -> MixerTrack | None:
        if not self.lock.acquire(blocking=False):
            return None
        try:
            return self.current
        finally:
            self.lock.release()

    def queued_tracks_nonblocking(self) -> tuple[MixerTrack, ...] | None:
        if not self.lock.acquire(blocking=False):
            return None
        try:
            queued = []
            if self.next_track:
                queued.append(self.next_track)
            queued.extend(self.queue)
            return tuple(queued)
        finally:
            self.lock.release()

    def _duration_locked(self, track: MixerTrack | None) -> float:
        if not track:
            return 0.0
        return track.effective_playable_duration or float(track.duration or 0)

    def _crossfade_locked(self, track: MixerTrack | None) -> float:
        if not track or self.crossfade_seconds <= 0:
            return 0.0
        planned = track.crossfade_seconds
        seconds = self.crossfade_seconds if planned is None else min(self.crossfade_seconds, planned)
        duration = self._duration_locked(track)
        if duration > 0:
            seconds = min(seconds, duration / 3)
        return max(0.0, min(15.0, seconds))

    def _start_next_locked(self) -> bool:
        while self.queue:
            track = self.queue.popleft()
            try:
                self.current = track
                self.current_stream = FFmpegPCMStream(track)
                self.current_elapsed = 0.0
                return True
            except Exception as e:
                self.last_error = f"{track.title}: {e}"
                self.current = None
                self.current_stream = None
        return False

    def _apply_pending_locked(self):
        if self.clear_requested:
            self.queue.clear()
            self._close_next_locked()
            self.clear_requested = False
        if self.skip_requested:
            self.skip_requested = False
            self._close_current_locked()
            if not self._promote_next_locked():
                self._start_next_locked()

    def _start_crossfade_locked(self):
        if self.next_stream or not self.queue:
            return
        track = self.queue.popleft()
        try:
            self.next_track = track
            self.next_stream = FFmpegPCMStream(track)
            self.next_elapsed = 0.0
        except Exception as e:
            self.last_error = f"{track.title}: {e}"
            self.next_track = None
            self.next_stream = None

    def _close_current_locked(self):
        if self.current_stream:
            self.current_stream.close()
        self.current = None
        self.current_stream = None
        self.current_elapsed = 0.0

    def _close_next_locked(self):
        if self.next_stream:
            self.next_stream.close()
        self.next_track = None
        self.next_stream = None
        self.next_elapsed = 0.0

    def _promote_next_locked(self) -> bool:
        if not self.next_stream or not self.next_track:
            return False
        self.current = self.next_track
        self.current_stream = self.next_stream
        self.current_elapsed = self.next_elapsed
        self.next_track = None
        self.next_stream = None
        self.next_elapsed = 0.0
        return True

    def _maybe_crossfade_locked(self):
        duration = self._duration_locked(self.current)
        crossfade_seconds = self._crossfade_locked(self.current)
        if not self.current or not duration or crossfade_seconds <= 0:
            return
        remaining = duration - self.current_elapsed
        if remaining <= crossfade_seconds:
            self._start_crossfade_locked()

    def _fade_progress_locked(self) -> float:
        duration = self._duration_locked(self.current)
        crossfade_seconds = self._crossfade_locked(self.current)
        if not self.current or not duration or crossfade_seconds <= 0:
            return 0.0
        remaining = max(0.0, duration - self.current_elapsed)
        return max(0.0, min(1.0, (crossfade_seconds - remaining) / crossfade_seconds))

    def _scale(self, frame: bytes, gain: float) -> bytes:
        gain = max(0.0, min(2.0, gain))
        if gain == 1.0:
            return frame
        return pcm_mul(frame, SAMPLE_WIDTH, gain)

    def _mix(self, current_frame: bytes, next_frame: bytes, progress: float) -> bytes:
        progress = max(0.0, min(1.0, progress))
        angle = progress * math.pi / 2
        current_gain = self.volume * math.cos(angle)
        next_gain = self.volume * math.sin(angle)
        if self.current:
            current_gain *= max(0.0, min(2.0, self.current.gain))
        if self.next_track:
            next_gain *= max(0.0, min(2.0, self.next_track.gain))
        return pcm_add(
            self._scale(current_frame, current_gain),
            self._scale(next_frame, next_gain),
            SAMPLE_WIDTH,
        )

    def read(self) -> bytes:
        with self.lock:
            if self.stopped:
                self.queue.clear()
                self._close_current_locked()
                self._close_next_locked()
                return b""

            self._apply_pending_locked()

            for _ in range(3):
                if not self.current_stream and not self._start_next_locked():
                    return b""

                try:
                    current_frame = self.current_stream.read_frame() if self.current_stream else None
                except Exception as e:
                    title = self.current.title if self.current else "current track"
                    self.last_error = f"{title}: {e}"
                    self._close_current_locked()
                    self._promote_next_locked()
                    continue
                if current_frame:
                    break

                self._close_current_locked()
                if not self._promote_next_locked():
                    continue
            else:
                return b""

            self._maybe_crossfade_locked()

            if self.next_stream:
                try:
                    next_frame = self.next_stream.read_frame()
                except Exception as e:
                    title = self.next_track.title if self.next_track else "next track"
                    self.last_error = f"{title}: {e}"
                    self._close_next_locked()
                    next_frame = None
                if next_frame:
                    progress = self._fade_progress_locked()
                    frame = self._mix(current_frame, next_frame, progress)
                    self.current_elapsed += FRAME_DURATION
                    self.next_elapsed += FRAME_DURATION
                    if progress >= 0.995:
                        self._close_current_locked()
                        self._promote_next_locked()
                    return frame

                self._close_next_locked()

            self.current_elapsed += FRAME_DURATION
            gain = self.volume
            if self.current:
                gain *= max(0.0, min(2.0, self.current.gain))
            return self._scale(current_frame, gain)

    def cleanup(self):
        self.stop()
