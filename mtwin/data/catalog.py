"""Cache catalogue: a small DuckDB-powered summary of what is stored locally."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd

DUCKDB_AVAILABLE = importlib.util.find_spec("duckdb") is not None
COLUMNS = ["dataset", "format", "rows", "first_date", "last_date", "source", "fetched_at"]


def describe_cache(root: Path) -> pd.DataFrame:
    """Summarise every cached dataset: row count, date coverage, source and fetch time.

    Uses DuckDB (``read_parquet``) when available and falls back to pandas otherwise.
    """
    rows: list[dict[str, object]] = []
    for meta_path in sorted(Path(root).glob("*.meta.json")):
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        data_path = meta_path.with_name(meta_path.name.replace(".meta.json", f".{meta['format']}"))
        if not data_path.exists():
            continue
        first, last = _date_range(data_path, meta)
        rows.append(
            {
                "dataset": meta["key"],
                "format": meta["format"],
                "rows": meta["rows"],
                "first_date": first,
                "last_date": last,
                "source": meta.get("source", ""),
                "fetched_at": meta.get("fetched_at", ""),
            }
        )
    return pd.DataFrame(rows, columns=COLUMNS)


def _date_range(data_path: Path, meta: dict) -> tuple[str, str]:
    date_cols = meta.get("datetime_cols") or []
    if not date_cols:
        return "", ""
    col = date_cols[0]
    if meta["format"] == "parquet" and DUCKDB_AVAILABLE:
        import duckdb

        query = f'SELECT min("{col}"), max("{col}") FROM read_parquet(?)'
        low, high = duckdb.execute(query, [str(data_path)]).fetchone()
        return str(low)[:10], str(high)[:10]
    frame = pd.read_parquet(data_path) if meta["format"] == "parquet" else pd.read_csv(data_path)
    values = pd.to_datetime(frame[col])
    return str(values.min())[:10], str(values.max())[:10]
