from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from .api_football import ApiFootballClient
from .settings import PROJECT_ROOT, env_bool, env_int, env_str


CACHEABLE_ENDPOINTS = {
    "fixtures",
    "fixtures/headtohead",
    "fixtures/statistics",
    "fixtures/events",
    "teams",
    "teams/statistics",
    "odds",
}

DEFAULT_CACHE_TTL_SECONDS = {
    "fixtures": 900,
    "fixtures/headtohead": 3600,
    "fixtures/statistics": 3600,
    "fixtures/events": 3600,
    "teams": 86400,
    "teams/statistics": 3600,
    "odds": 300,
}


class CachedApiFootballClient(ApiFootballClient):
    def __init__(
        self,
        api_key: str | None = None,
        *,
        cache_dir: str | Path | None = None,
        cache_enabled: bool | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(api_key=api_key, **kwargs)
        configured_dir = cache_dir or env_str("WORLDCUP_DATA_CACHE_DIR", "storage/api_cache")
        self.cache_dir = Path(configured_dir)
        if not self.cache_dir.is_absolute():
            self.cache_dir = PROJECT_ROOT / self.cache_dir
        self.cache_enabled = env_bool("WORLDCUP_DATA_CACHE_ENABLED", True) if cache_enabled is None else cache_enabled
        self.cache_hits = 0
        self.cache_misses = 0

    def get(self, endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        normalized_endpoint = endpoint.strip().lstrip("/")
        if not self.cache_enabled or normalized_endpoint not in CACHEABLE_ENDPOINTS:
            return super().get(endpoint, params)

        path = self._cache_path(normalized_endpoint, params or {})
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if self._is_cache_fresh(path, normalized_endpoint):
                    self.logical_requests += 1
                    self.cache_hits += 1
                    return data
            except (OSError, json.JSONDecodeError):
                pass

        self.cache_misses += 1
        data = super().get(endpoint, params)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return data

    def _cache_path(self, endpoint: str, params: dict[str, Any]) -> Path:
        clean_endpoint = endpoint.replace("/", "_")
        normalized = json.dumps(
            {
                "endpoint": endpoint,
                "params": {key: params[key] for key in sorted(params) if params[key] is not None},
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]
        return self.cache_dir / clean_endpoint / f"{digest}.json"

    def _is_cache_fresh(self, path: Path, endpoint: str) -> bool:
        ttl = self._cache_ttl_seconds(endpoint)
        if ttl <= 0:
            return True
        try:
            age = max(0.0, time.time() - path.stat().st_mtime)
        except OSError:
            return False
        return age <= ttl

    def _cache_ttl_seconds(self, endpoint: str) -> int:
        env_key = "WORLDCUP_DATA_CACHE_TTL_" + endpoint.upper().replace("/", "_") + "_SECONDS"
        override = env_int(env_key, -1)
        if override >= 0:
            return override
        default_ttl = DEFAULT_CACHE_TTL_SECONDS.get(endpoint, 0)
        return env_int("WORLDCUP_DATA_CACHE_TTL_SECONDS", default_ttl)


def build_data_layer_client(api_key: str | None = None) -> CachedApiFootballClient:
    return CachedApiFootballClient(api_key=api_key)
