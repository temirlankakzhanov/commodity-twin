"""Snapshot the raw (uncleaned) FRED WTI series for 2020, used only by the landing page chart.

The model never reads this file: ``mtwin.data.transforms.clean_prices`` treats the negative
print of 2020-04-20 as missing and carries the previous price forward. The landing page shows
the raw print next to a note that explains this documented handling.

Usage: ``python scripts/snapshot_raw_wti.py`` (network) writes
``data/snapshots/site-raw-DCOILWTICO-2020.csv``.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from mtwin.config import load_settings
from mtwin.data.http import HttpClient
from mtwin.data.providers.fred import FredProvider

SERIES_ID = "DCOILWTICO"
START, END = "2020-01-01", "2020-12-31"
OUT = Path(__file__).resolve().parents[1] / "data" / "snapshots" / "site-raw-DCOILWTICO-2020.csv"


def raw_frame(series: pd.Series) -> pd.DataFrame:
    """Two-column frame (``date``, ``WTI``) exactly as FRED reported it, negatives included."""
    frame = series.rename("WTI").to_frame().reset_index()
    frame["date"] = frame["date"].dt.strftime("%Y-%m-%d")
    return frame


def main() -> None:
    """Fetch the raw series and write the snapshot."""
    settings = load_settings()
    fred = FredProvider(HttpClient(settings), settings.fred_api_key)
    frame = raw_frame(fred.fetch_series(SERIES_ID, start=START, end=END))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(OUT, index=False)
    print(f"{len(frame)} rows, min {frame['WTI'].min()} -> {OUT}")


if __name__ == "__main__":
    main()
