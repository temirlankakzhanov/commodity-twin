"""Local on-disk cache for tidy DataFrames.

Frames are stored as Parquet (via ``pyarrow``) with a small JSON sidecar that records when and
from where the data was fetched. When ``pyarrow`` is not installed the cache degrades to
gzip-compressed CSV so that development environments without it keep working; the public
behaviour is identical.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import logging
import math
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

PARQUET_AVAILABLE = importlib.util.find_spec("pyarrow") is not None


@dataclass(frozen=True)
class CacheEntry:
    """A cached frame together with its provenance."""

    data: pd.DataFrame
    fetched_at: datetime
    fresh: bool
    source: str


def _slug(key: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", key).strip("_")[:80] or "key"
    digest = hashlib.sha1(key.encode("utf-8"), usedforsecurity=False).hexdigest()[:8]
    return f"{safe}-{digest}"


class ParquetCache:
    """Key-value cache for DataFrames with a time-to-live.

    ``ttl_hours=math.inf`` makes every entry permanently fresh, which is how committed data
    snapshots are read.
    """

    def __init__(
        self,
        root: Path,
        ttl_hours: float,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._root = Path(root)
        self._ttl_hours = ttl_hours
        self._now = now or (lambda: datetime.now(UTC))

    @property
    def root(self) -> Path:
        """Directory holding the cache files."""
        return self._root

    def put(self, key: str, df: pd.DataFrame, source: str = "") -> None:
        """Store ``df`` under ``key`` atomically (write to a temp file, then rename)."""
        self._root.mkdir(parents=True, exist_ok=True)
        frame = df
        if isinstance(frame.index, pd.DatetimeIndex) and frame.index.name is None:
            frame = frame.rename_axis("date")
        index_names = [name for name in frame.index.names if name is not None]
        flat = frame.reset_index() if index_names else frame.reset_index(drop=True)
        flat.columns = [str(col) for col in flat.columns]
        datetime_cols = [
            col for col in flat.columns if pd.api.types.is_datetime64_any_dtype(flat[col])
        ]

        base = self._root / _slug(key)
        fmt = "parquet" if PARQUET_AVAILABLE else "csv.gz"
        data_path = base.with_name(f"{base.name}.{fmt}")
        tmp_path = base.with_name(f"{base.name}.tmp.{fmt}")
        if fmt == "parquet":
            flat.to_parquet(tmp_path, index=False)
        else:
            flat.to_csv(tmp_path, index=False, compression="gzip")
        os.replace(tmp_path, data_path)

        meta = {
            "key": key,
            "format": fmt,
            "source": source,
            "rows": len(flat),
            "fetched_at": self._now().isoformat(),
            "index": index_names,
            "datetime_cols": datetime_cols,
        }
        meta_tmp = base.with_name(f"{base.name}.meta.tmp")
        meta_tmp.write_text(json.dumps(meta), encoding="utf-8")
        os.replace(meta_tmp, base.with_name(f"{base.name}.meta.json"))

    def get(self, key: str, *, allow_stale: bool = True) -> CacheEntry | None:
        """Return the entry for ``key`` or ``None`` when missing, corrupt or (optionally) stale."""
        base = self._root / _slug(key)
        meta_path = base.with_name(f"{base.name}.meta.json")
        if not meta_path.exists():
            return None
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            data_path = base.with_name(f"{base.name}.{meta['format']}")
            if meta["format"] == "parquet":
                flat = pd.read_parquet(data_path)
            else:
                flat = pd.read_csv(data_path, compression="gzip")
            for col in meta.get("datetime_cols", []):
                flat[col] = pd.to_datetime(flat[col])
            if meta.get("index"):
                flat = flat.set_index(meta["index"])
            fetched_at = datetime.fromisoformat(meta["fetched_at"])
        except (OSError, ValueError, KeyError, ImportError) as exc:
            logger.warning("Ignoring unreadable cache entry %s: %s", key, type(exc).__name__)
            return None

        fresh = self._is_fresh(fetched_at)
        if not fresh and not allow_stale:
            return None
        return CacheEntry(flat, fetched_at, fresh, str(meta.get("source", "")))

    def _is_fresh(self, fetched_at: datetime) -> bool:
        if math.isinf(self._ttl_hours):
            return True
        return self._now() - fetched_at < timedelta(hours=self._ttl_hours)

    def clear(self) -> None:
        """Delete every cache file."""
        if not self._root.exists():
            return
        for path in self._root.iterdir():
            if path.is_file():
                path.unlink()
