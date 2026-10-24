"""Data-quality transforms shared by all price providers."""

from __future__ import annotations

import pandas as pd

from mtwin.data.errors import DataError


def clean_prices(prices: pd.DataFrame, *, max_ffill: int = 5, min_rows: int = 250) -> pd.DataFrame:
    """Return a clean, strictly positive, gap-filled price frame.

    Rules (documented in ``docs/methodology.md``):

    1. Sort by date and drop duplicate dates (last value wins).
    2. Non-positive prices become missing. WTI printed a negative price on 2020-04-20, and
       log returns are undefined for such values. The following valid print therefore carries
       the full multi-day move instead of producing ``NaN``.
    3. Forward-fill gaps of at most ``max_ffill`` observations (exchange holidays).
    4. Drop any remaining row that still has a missing value.

    Raises:
        DataError: if fewer than ``min_rows`` rows survive.
    """
    frame = prices.sort_index()
    frame = frame[~frame.index.duplicated(keep="last")]
    frame = frame.where(frame > 0).ffill(limit=max_ffill).dropna(how="any")
    if len(frame) < min_rows:
        raise DataError(f"Only {len(frame)} usable price rows after cleaning (need {min_rows}).")
    frame = frame.copy()
    frame.index.name = "date"
    return frame
