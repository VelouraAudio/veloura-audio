"""Stream URL resolution for the Veloura audio engine."""

import asyncio
import json
import sys
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


def _extract_stream_info(query: str, options: dict) -> dict:
    yt_dlp = require_yt_dlp()
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(query, download=False)
        if info and info.get("entries"):
            info = next((entry for entry in info["entries"] if entry), None)
        if not info:
            raise RuntimeError("No result found.")

        stream_url = info.get("url")
        if not stream_url:
            raise RuntimeError("No stream URL found.")

        return {
            "title": info.get("title"),
            "url": stream_url,
            "webpage_url": info.get("webpage_url"),
            "original_url": info.get("original_url"),
            "duration": info.get("duration"),
        }


async def _stop_process(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    try:
        process.terminate()
    except ProcessLookupError:
        return
    try:
        await asyncio.wait_for(process.wait(), timeout=1.0)
    except TimeoutError:
        try:
            process.kill()
        except ProcessLookupError:
            return
        await process.wait()


async def _run_json_worker(
    command: tuple[str, ...],
    request: dict,
    *,
    timeout: float,
) -> dict:
    try:
        encoded_request = json.dumps(request, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "ydl_options must contain JSON-compatible values when timeout is enabled."
        ) from exc

    process = await asyncio.create_subprocess_exec(
        *command,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(encoded_request),
            timeout=timeout,
        )
    except TimeoutError:
        await _stop_process(process)
        raise TimeoutError(f"stream resolution exceeded {timeout:g} seconds.") from None
    except BaseException:
        await _stop_process(process)
        raise

    try:
        response = json.loads(stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        detail = stderr.decode("utf-8", "replace").strip()[-2000:]
        message = "yt-dlp worker returned an invalid response."
        if detail:
            message = f"{message} {detail}"
        raise RuntimeError(message) from exc

    if not isinstance(response, dict):
        raise RuntimeError("yt-dlp worker returned an invalid response.")
    if process.returncode != 0 or not response.get("ok"):
        error = str(response.get("error") or "yt-dlp failed to resolve the stream.")
        raise RuntimeError(error)
    info = response.get("info")
    if not isinstance(info, dict):
        raise RuntimeError("yt-dlp worker returned invalid stream metadata.")
    return info


async def _resolve_with_worker(query: str, options: dict, timeout: float) -> dict:
    if timeout <= 0:
        raise ValueError("timeout must be greater than zero.")
    require_yt_dlp()
    return await _run_json_worker(
        (sys.executable, "-m", "veloura.audio._resolver_worker"),
        {"query": query, "options": options},
        timeout=timeout,
    )


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
    validate_query_scheme(query, allowed_url_schemes)
    options = dict(YDL_STREAM_OPTIONS)
    if ydl_options:
        options.update(ydl_options)

    if timeout is None:
        info = await asyncio.to_thread(_extract_stream_info, query, options)
    else:
        info = await _resolve_with_worker(query, options, float(timeout))

    title = info.get("title") or fallback_title or query
    webpage = info.get("webpage_url") or info.get("original_url") or fallback_webpage or query
    duration = float(info.get("duration") or fallback_duration or 0)
    track = MixerTrack(
        title=title,
        stream_url=info["url"],
        webpage=webpage,
        duration=duration,
        requester_id=requester_id,
        payload=payload,
    )
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
