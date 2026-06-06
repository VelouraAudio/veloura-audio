"""File-based analysis cache for Veloura."""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from .models import AudioTrack
from .transition import SmartTransitionConfig, normalize_transition_config, prepare_smart_transition

CACHE_SCHEMA_VERSION = 1


def default_cache_dir() -> Path:
    configured = os.getenv("VELOURA_CACHE_DIR")
    if configured:
        return Path(configured).expanduser()
    xdg_cache = os.getenv("XDG_CACHE_HOME")
    if xdg_cache:
        return Path(xdg_cache).expanduser() / "veloura"
    return Path.home() / ".cache" / "veloura"


def stable_json_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def source_signature(source: str) -> dict[str, Any]:
    path = Path(source).expanduser()
    if path.exists():
        try:
            stat = path.stat()
            return {
                "kind": "file",
                "path": str(path.resolve()),
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
            }
        except OSError:
            pass
    return {"kind": "source", "source": source}


def config_payload(config: SmartTransitionConfig) -> dict[str, Any]:
    normalized = normalize_transition_config(config)
    if is_dataclass(normalized):
        return asdict(normalized)
    return dict(normalized)  # pragma: no cover - defensive fallback


def build_transition_cache_key(track: AudioTrack, config: SmartTransitionConfig) -> str:
    return stable_json_hash(
        {
            "schema": CACHE_SCHEMA_VERSION,
            "type": "transition",
            "source": source_signature(track.stable_id),
            "duration": round(float(track.duration or 0.0), 3),
            "title": track.title,
            "config": config_payload(config),
        }
    )


class FileAnalysisCache:
    """Small JSON cache for reusable transition analysis.

    The cache is intentionally app-agnostic: it stores only Veloura analysis
    payloads keyed by source/config fingerprints.
    """

    def __init__(self, root: str | os.PathLike[str] | None = None):
        self.root = Path(root).expanduser() if root else default_cache_dir()

    def path_for(self, kind: str, key: str) -> Path:
        safe_kind = "".join(ch for ch in kind if ch.isalnum() or ch in {"-", "_"}) or "analysis"
        return self.root / safe_kind / f"{key}.json"

    def get_json(self, kind: str, key: str) -> dict[str, Any] | None:
        path = self.path_for(kind, key)
        try:
            with path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return None
        if data.get("schema") != CACHE_SCHEMA_VERSION:
            return None
        payload = data.get("payload")
        return payload if isinstance(payload, dict) else None

    def set_json(self, kind: str, key: str, payload: dict[str, Any]) -> Path:
        path = self.path_for(kind, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(".tmp")
        document = {
            "schema": CACHE_SCHEMA_VERSION,
            "kind": kind,
            "created_at": round(time.time(), 3),
            "payload": payload,
        }
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(document, handle, sort_keys=True, separators=(",", ":"))
        tmp_path.replace(path)
        return path

    def get_transition_analysis(self, track: AudioTrack, config: SmartTransitionConfig) -> dict[str, Any] | None:
        return self.get_json("transition", build_transition_cache_key(track, config))

    def set_transition_analysis(
        self,
        track: AudioTrack,
        config: SmartTransitionConfig,
        analysis: dict[str, Any],
    ) -> Path:
        return self.set_json("transition", build_transition_cache_key(track, config), dict(analysis))

    def prepare_transition(self, track: AudioTrack, config: SmartTransitionConfig | None) -> AudioTrack:
        if not config or not config.enabled:
            return prepare_smart_transition(track, config)

        cached = self.get_transition_analysis(track, config)
        prepared = prepare_smart_transition(track, config, cached)
        if prepared.analysis and not prepared.analysis.get("cached"):
            self.set_transition_analysis(prepared, config, prepared.analysis)
        return prepared
