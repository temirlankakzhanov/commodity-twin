"""FRED (Federal Reserve Bank of St. Louis) provider.

Without an API key the public ``fredgraph.csv`` endpoint is used; with ``FRED_API_KEY`` the
official JSON API is used instead. Both paths return a ``pandas.Series`` with a ``DatetimeIndex``.
"""

from __future__ import annotations

import io
from typing import Any

import pandas as pd

from mtwin.data.errors import ProviderError
from mtwin.data.http import HttpClient

CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
API_URL = "https://api.stlouisfed.org/fred/series/observations"


def parse_fred_csv(text: str, series_id: str) -> pd.Series:
    """Parse a ``fredgraph.csv`` body.

    The header of the date column has been ``DATE`` and ``observation_date`` at different
    times, so the first column is treated as the date. Missing values are encoded as ``.``.
    HTML bodies (for example a maintenance page) are rejected.
    """
    stripped = text.lstrip()
    if not stripped or stripped.startswith("<"):
        raise ProviderError(f"FRED returned a non-CSV response for {series_id}")
    try:
        frame = pd.read_csv(io.StringIO(text))
    except (pd.errors.ParserError, pd.errors.EmptyDataError):
        raise ProviderError(f"FRED CSV for {series_id} could not be parsed") from None
    if frame.shape[1] < 2:
        raise ProviderError(f"FRED CSV for {series_id} has an unexpected layout")
    value_col = series_id if series_id in frame.columns else frame.columns[1]
    return _to_series(frame.iloc[:, 0], frame[value_col], series_id)


def parse_fred_api_json(payload: Any, series_id: str) -> pd.Series:
    """Parse the JSON returned by ``/fred/series/observations``."""
    if not isinstance(payload, dict) or "observations" not in payload:
        detail = "unexpected payload"
        if isinstance(payload, dict) and payload.get("error_message"):
            detail = str(payload["error_message"])
        raise ProviderError(f"FRED API error for {series_id}: {detail}")
    rows = payload["observations"]
    return _to_series(
        pd.Series([row.get("date") for row in rows], dtype="object"),
        pd.Series([row.get("value") for row in rows], dtype="object"),
        series_id,
    )


def _to_series(dates: pd.Series, values: pd.Series, series_id: str) -> pd.Series:
    index = pd.DatetimeIndex(pd.to_datetime(dates, errors="coerce"), name="date")
    numeric = pd.to_numeric(values, errors="coerce")
    series = pd.Series(numeric.to_numpy(dtype=float), index=index, name=series_id)
    series = series[series.index.notna()].dropna().sort_index()
    if series.empty:
        raise ProviderError(f"FRED returned no observations for {series_id}")
    return series


class FredProvider:
    """Download daily series from FRED."""

    name = "FRED"

    def __init__(self, http: HttpClient, api_key: str | None = None) -> None:
        self._http = http
        self._api_key = api_key

    def fetch_series(
        self, series_id: str, start: str | None = None, end: str | None = None
    ) -> pd.Series:
        """Fetch one series, optionally restricted to ``[start, end]`` (ISO dates)."""
        if self._api_key:
            params: dict[str, Any] = {
                "series_id": series_id,
                "api_key": self._api_key,
                "file_type": "json",
            }
            if start:
                params["observation_start"] = start
            if end:
                params["observation_end"] = end
            series = parse_fred_api_json(self._http.get_json(API_URL, params), series_id)
        else:
            params = {"id": series_id}
            if start:
                params["cosd"] = start
            if end:
                params["coed"] = end
            series = parse_fred_csv(self._http.get_text(CSV_URL, params), series_id)
        if start:
            series = series[series.index >= pd.Timestamp(start)]
        if end:
            series = series[series.index <= pd.Timestamp(end)]
        if series.empty:
            raise ProviderError(f"FRED returned no observations for {series_id} in the window")
        return series
