"""Isolated yt-dlp worker used by timed stream resolution."""

from __future__ import annotations

import json
import sys

from .resolver import _extract_stream_info

MAX_REQUEST_BYTES = 1_048_576


class _QuietLogger:
    def debug(self, _message: str) -> None:
        pass

    def info(self, _message: str) -> None:
        pass

    def warning(self, _message: str) -> None:
        pass

    def error(self, _message: str) -> None:
        pass


def _write_response(response: dict) -> None:
    json.dump(response, sys.stdout, separators=(",", ":"))
    sys.stdout.flush()


def main() -> int:
    raw_request = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
    if len(raw_request) > MAX_REQUEST_BYTES:
        _write_response({"ok": False, "error": "yt-dlp worker request is too large."})
        return 1

    try:
        request = json.loads(raw_request.decode("utf-8"))
        query = request["query"]
        options = request["options"]
        if not isinstance(query, str) or not query.strip():
            raise ValueError("stream query must be a non-empty string.")
        if not isinstance(options, dict):
            raise ValueError("yt-dlp options must be a mapping.")
        options = dict(options)
        options["logger"] = _QuietLogger()
        info = _extract_stream_info(query, options)
    except Exception as exc:
        _write_response({"ok": False, "error": str(exc) or type(exc).__name__})
        return 1

    _write_response({"ok": True, "info": info})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
