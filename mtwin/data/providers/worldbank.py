"""World Bank Indicators API provider (``api.worldbank.org/v2``)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pandas as pd

from mtwin.data.errors import ProviderError
from mtwin.data.http import HttpClient

BASE_URL = "https://api.worldbank.org/v2"
COLUMNS = ["country_iso3", "country", "indicator", "year", "value"]
PER_PAGE = 5000
MAX_PAGES = 20


def parse_worldbank(payload: Any) -> tuple[pd.DataFrame, int]:
    """Parse one page of the API response.

    The API answers ``[metadata, records]``. Errors come back as ``[{"message": [...]}]``.
    Records with a null ``value`` are dropped.

    Returns:
        The tidy frame for this page and the total number of pages.
    """
    if not isinstance(payload, list) or not payload or not isinstance(payload[0], dict):
        raise ProviderError("World Bank API returned an unexpected payload")
    meta = payload[0]
    if "message" in meta:
        raise ProviderError("World Bank API reported an error for this request")
    rows = payload[1] if len(payload) > 1 and payload[1] else []
    records = []
    for row in rows:
        value = row.get("value")
        if value is None:
            continue
        country = row.get("country") or {}
        records.append(
            {
                "country_iso3": row.get("countryiso3code") or country.get("id"),
                "country": country.get("value"),
                "indicator": (row.get("indicator") or {}).get("id"),
                "year": int(row["date"]),
                "value": float(value),
            }
        )
    return pd.DataFrame(records, columns=COLUMNS), int(meta.get("pages", 1))


class WorldBankProvider:
    """Download annual indicators for a set of countries."""

    name = "World Bank"

    def __init__(self, http: HttpClient) -> None:
        self._http = http

    def fetch_indicator(
        self, countries: Sequence[str], indicator: str, start_year: int, end_year: int
    ) -> pd.DataFrame:
        """Fetch one indicator for several ISO3 country codes."""
        url = f"{BASE_URL}/country/{';'.join(countries)}/indicator/{indicator}"
        frames: list[pd.DataFrame] = []
        page, pages = 1, 1
        while page <= pages and page <= MAX_PAGES:
            payload = self._http.get_json(
                url,
                {
                    "format": "json",
                    "date": f"{start_year}:{end_year}",
                    "per_page": PER_PAGE,
                    "page": page,
                },
            )
            frame, pages = parse_worldbank(payload)
            frames.append(frame)
            page += 1
        result = pd.concat(frames, ignore_index=True)
        if result.empty:
            raise ProviderError(f"World Bank returned no data for {indicator}")
        return result

    def fetch_indicators(
        self, countries: Sequence[str], indicators: Sequence[str], start_year: int, end_year: int
    ) -> pd.DataFrame:
        """Fetch several indicators and stack them into one tidy frame."""
        frames = [
            self.fetch_indicator(countries, indicator, start_year, end_year)
            for indicator in indicators
        ]
        return pd.concat(frames, ignore_index=True)
