"""Runtime configuration read from environment variables.

All tunables live here so the rest of the code base never touches ``os.environ`` directly.
Secrets (for example ``FRED_API_KEY``) are read from the environment only and are never
written to logs, caches or error messages.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    """Immutable application settings."""

    cache_dir: Path
    snapshot_dir: Path
    http_timeout_s: float = 8.0
    http_retries: int = 2
    http_backoff_s: float = 0.6
    cache_ttl_hours: float = 12.0
    provider_cooldown_s: float = 300.0
    offline: bool = False
    enable_yahoo: bool = False
    fred_api_key: str | None = None
    user_agent: str = "commodity-twin/0.1 (open-source research project)"


def load_settings() -> Settings:
    """Build :class:`Settings` from the process environment.

    Recognised variables: ``MTWIN_CACHE_DIR``, ``MTWIN_SNAPSHOT_DIR``, ``MTWIN_OFFLINE``,
    ``MTWIN_ENABLE_YAHOO``, ``MTWIN_HTTP_TIMEOUT_S``, ``MTWIN_HTTP_RETRIES``,
    ``MTWIN_CACHE_TTL_HOURS`` and ``FRED_API_KEY``.
    """
    return Settings(
        cache_dir=Path(os.environ.get("MTWIN_CACHE_DIR", PROJECT_ROOT / ".cache" / "mtwin")),
        snapshot_dir=Path(
            os.environ.get("MTWIN_SNAPSHOT_DIR", PROJECT_ROOT / "data" / "snapshots")
        ),
        http_timeout_s=float(os.environ.get("MTWIN_HTTP_TIMEOUT_S", "8")),
        http_retries=int(os.environ.get("MTWIN_HTTP_RETRIES", "2")),
        cache_ttl_hours=float(os.environ.get("MTWIN_CACHE_TTL_HOURS", "12")),
        offline=_env_bool("MTWIN_OFFLINE"),
        enable_yahoo=_env_bool("MTWIN_ENABLE_YAHOO"),
        fred_api_key=os.environ.get("FRED_API_KEY") or None,
    )
