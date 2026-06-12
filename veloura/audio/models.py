"""Audio engine data models."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AudioTrack:
    """A playable audio item for Veloura's engine.

    ``requester_id`` and ``payload`` are kept optional so Discord bots can attach
    user/context state, while non-Discord projects can ignore them completely.
    """

    title: str
    stream_url: str
    webpage: str = ""
    duration: float = 0.0
    requester_id: int = 0
    payload: Any | None = None
    artist: str | None = None
    album: str | None = None
    artwork_url: str | None = None
    source_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    trim_start: float = 0.0
    trim_end: float = 0.0
    crossfade_seconds: float | None = None
    gain: float = 1.0
    tempo: float = 1.0
    analysis: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_source(
        cls,
        source: str,
        *,
        title: str | None = None,
        webpage: str | None = None,
        duration: float | int | None = None,
        requester_id: int = 0,
        payload: Any | None = None,
        artist: str | None = None,
        album: str | None = None,
        artwork_url: str | None = None,
        source_id: str = "",
        trim_start: float = 0.0,
        trim_end: float = 0.0,
        crossfade_seconds: float | None = None,
        gain: float = 1.0,
        tempo: float = 1.0,
        analysis: dict[str, Any] | None = None,
        **metadata: Any,
    ) -> "AudioTrack":
        """Build a generic track from a local path, direct URL, or stream URL."""

        return cls(
            title=title or source,
            stream_url=source,
            webpage=webpage or source,
            duration=float(duration or 0.0),
            requester_id=requester_id,
            payload=payload,
            artist=artist,
            album=album,
            artwork_url=artwork_url,
            source_id=source_id,
            metadata=dict(metadata),
            trim_start=max(0.0, float(trim_start or 0.0)),
            trim_end=max(0.0, float(trim_end or 0.0)),
            crossfade_seconds=crossfade_seconds,
            gain=float(gain or 1.0),
            tempo=float(tempo or 1.0),
            analysis=dict(analysis or {}),
        )

    @property
    def stable_id(self) -> str:
        return self.source_id or self.webpage or self.stream_url or self.title

    @property
    def playable_duration(self) -> float:
        duration = float(self.duration or 0)
        if duration <= 0:
            return 0.0
        return max(0.0, duration - max(0.0, self.trim_start) - max(0.0, self.trim_end))

    @property
    def tempo_ratio(self) -> float:
        try:
            tempo = float(self.tempo or 1.0)
        except (TypeError, ValueError):
            return 1.0
        if tempo <= 0:
            return 1.0
        return max(0.5, min(2.0, tempo))

    @property
    def effective_playable_duration(self) -> float:
        duration = self.playable_duration
        if duration <= 0:
            return 0.0
        return duration / self.tempo_ratio


# Backwards-compatible name used by the Discord bot and older Veloura examples.
MixerTrack = AudioTrack
