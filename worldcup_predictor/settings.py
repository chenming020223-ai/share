from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_dotenv(path: str | Path | None = None) -> None:
    """Load a tiny .env file without adding a runtime dependency."""
    env_path = Path(path) if path else PROJECT_ROOT / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def env_str(name: str, default: str = "") -> str:
    load_dotenv()
    return os.getenv(name, default)


def env_int(name: str, default: int) -> int:
    value = env_str(name, "")
    try:
        return int(value)
    except ValueError:
        return default


def env_bool(name: str, default: bool = False) -> bool:
    value = env_str(name, "")
    if not value:
        return default
    return value.casefold() in {"1", "true", "yes", "y", "on", "是"}


def env_list(name: str, default: list[str] | tuple[str, ...] | None = None) -> list[str]:
    value = env_str(name, "")
    if not value:
        return list(default or [])
    parts = value.replace(";", ",").split(",")
    items: list[str] = []
    seen: set[str] = set()
    for part in parts:
        item = part.strip()
        if not item:
            continue
        key = item.casefold()
        if key in seen:
            continue
        seen.add(key)
        items.append(item)
    return items


def default_db_path() -> Path:
    configured = env_str("WORLDCUP_DB_PATH", "storage/worldcup_predictor.sqlite3")
    path = Path(configured)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path
