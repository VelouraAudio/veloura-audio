"""Stream URL resolution for the Veloura audio engine."""

import asyncio
from urllib.parse import urlparse

from .cache import FileAnalysisCache
from .constants import YDL_STREAM_OPTIONS
from .models import MixerTrack
from .transition import SmartTransitionConfig, prepare_smart_transition

DEFAULT_ALLOWED_URL_SCHEMES = ("http", "https")


def require_yt_dlp():
    try:
        import yt_dlp
    except ImportError as exc:
        raise RuntimeError(
            "yt-dlp is required to resolve stream URLs. Install Veloura with "
            "'veloura-audio[stream]' or install yt-dlp separately."
        ) from exc
    return yt_dlp


def validate_query_scheme(query: str, allowed_url_schemes: tuple[str, ...] | None) -> None:
    if not allowed_url_schemes:
        return
    parsed = urlparse(query)
    if not parsed.scheme:
        return
    if "://" not in query and parsed.scheme not in {"file", "ftp", "sftp"}:
        return
    allowed = {scheme.lower() for scheme in allowed_url_schemes}
    if parsed.scheme.lower() not in allowed:
        raise ValueError(f"unsupported URL scheme for stream resolution: {parsed.scheme}")


async def resolve_stream_track(
    query: str,
    requester_id: int = 0,
    *,
    payload=None,
    fallback_title: str | None = None,
    fallback_webpage: str | None = None,
    fallback_duration: float | int | None = None,
    transition_config: SmartTransitionConfig | None = None,
    cached_transition_analysis: dict | None = None,
    analysis_cache: FileAnalysisCache | None = None,
    timeout: float | None = None,
    ydl_options: dict | None = None,
    allowed_url_schemes: tuple[str, ...] | None = DEFAULT_ALLOWED_URL_SCHEMES,
) -> MixerTrack:
    def resolve() -> MixerTrack:
        yt_dlp = require_yt_dlp()
        validate_query_scheme(query, allowed_url_schemes)
        options = dict(YDL_STREAM_OPTIONS)
        if ydl_options:
            options.update(ydl_options)
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(query, download=False)
            if info and info.get("entries"):
                info = next((entry for entry in info["entries"] if entry), None)
            if not info:
                raise RuntimeError("No result found.")

            stream_url = info.get("url")
            if not stream_url:
                raise RuntimeError("No stream URL found.")

            title = info.get("title") or fallback_title or query
            webpage = info.get("webpage_url") or info.get("original_url") or fallback_webpage or query
            duration = float(info.get("duration") or fallback_duration or 0)
            return MixerTrack(
                title=title,
                stream_url=stream_url,
                webpage=webpage,
                duration=duration,
                requester_id=requester_id,
                payload=payload,
            )

    resolution = asyncio.to_thread(resolve)
    track = await asyncio.wait_for(resolution, timeout=timeout) if timeout else await resolution
    if transition_config:
        if analysis_cache and not cached_transition_analysis:
            analysis = asyncio.to_thread(analysis_cache.prepare_transition, track, transition_config)
        else:
            analysis = asyncio.to_thread(
                prepare_smart_transition,
                track,
                transition_config,
                cached_transition_analysis,
            )
        track = await asyncio.wait_for(analysis, timeout=timeout) if timeout else await analysis
    return track
