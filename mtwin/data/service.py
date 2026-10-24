"""Data service: one place that knows how to obtain each dataset reliably.

Every dataset is resolved through the same fallback chain::

    fresh cache -> live provider -> stale cache -> committed snapshot -> synthetic data

so the application keeps working when an API is down, rate-limited or blocked. The source of
every result is reported in :class:`LoadResult` so the UI can state it honestly.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from typing import Literal

import pandas as pd

from mtwin.config import Settings, load_settings
from mtwin.data.cache import ParquetCache
from mtwin.data.errors import DataError
from mtwin.data.http import HttpClient
from mtwin.data.providers import (
    FredProvider,
    PortWatchProvider,
    WorldBankProvider,
    YahooProvider,
)
from mtwin.data.synthetic import synthetic_chokepoints, synthetic_prices, synthetic_worldbank
from mtwin.data.transforms import clean_prices

logger = logging.getLogger(__name__)

Source = Literal["live", "cache", "stale-cache", "snapshot", "synthetic"]

PRICE_SERIES = {"BRENT": "DCOILBRENTEU", "WTI": "DCOILWTICO", "HENRY_HUB": "DHHNGSP"}
YAHOO_TICKERS = {"BRENT": "BZ=F", "WTI": "CL=F", "HENRY_HUB": "NG=F"}
DEFAULT_START = "2010-01-01"
CHOKEPOINTS = (
    "Suez Canal",
    "Bab el-Mandeb Strait",
    "Strait of Hormuz",
    "Panama Canal",
    "Malacca Strait",
    "Cape of Good Hope",
)
WB_COUNTRIES = ("KAZ", "CHN", "USA", "DEU", "NLD", "SGP", "SAU", "ARE")
WB_INDICATORS = {"NE.TRD.GNFS.ZS": "Trade (% of GDP)", "NY.GDP.MKTP.CD": "GDP (current US$)"}
WB_START_YEAR = 2005


@dataclass(frozen=True)
class LoadResult:
    """A dataset plus where it came from."""

    data: pd.DataFrame
    source: Source
    label: str
    fetched_at: datetime | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)
    key: str = ""

    @property
    def is_real(self) -> bool:
        """True unless the data is synthetic."""
        return self.source != "synthetic"


class DataService:
    """Resolve datasets through cache, live providers, snapshots and synthetic fallbacks."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        http: HttpClient | None = None,
        cache: ParquetCache | None = None,
        snapshots: ParquetCache | None = None,
        fred: FredProvider | None = None,
        worldbank: WorldBankProvider | None = None,
        portwatch: PortWatchProvider | None = None,
        yahoo: YahooProvider | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._settings = settings or load_settings()
        client = http or HttpClient(self._settings)
        self._cache = cache or ParquetCache(
            self._settings.cache_dir, self._settings.cache_ttl_hours
        )
        self._snapshots = snapshots or ParquetCache(self._settings.snapshot_dir, float("inf"))
        self._fred = fred or FredProvider(client, self._settings.fred_api_key)
        self._worldbank = worldbank or WorldBankProvider(client)
        self._portwatch = portwatch or PortWatchProvider(client)
        self._yahoo = yahoo or YahooProvider()
        self._monotonic = monotonic
        self._cooldown_until: dict[str, float] = {}

    # ------------------------------------------------------------------ public datasets

    def prices(self, *, force_synthetic: bool = False, refresh: bool = False) -> LoadResult:
        """Daily BRENT, WTI and HENRY_HUB prices in USD (cleaned)."""

        def fetch() -> tuple[pd.DataFrame, str]:
            try:
                series = {
                    name: self._fred.fetch_series(series_id, start=DEFAULT_START)
                    for name, series_id in PRICE_SERIES.items()
                }
                return clean_prices(pd.concat(series, axis=1)), self._fred.name
            except DataError:
                if not self._settings.enable_yahoo:
                    raise
                logger.info("FRED failed; trying the optional Yahoo provider")
                frame = self._yahoo.fetch_close(YAHOO_TICKERS, start=DEFAULT_START)
                return clean_prices(frame), self._yahoo.name

        return self._resolve(
            key="prices-" + "-".join(PRICE_SERIES),
            provider="FRED",
            fetch=fetch,
            synthetic=lambda: synthetic_prices(DEFAULT_START),
            force_synthetic=force_synthetic,
            refresh=refresh,
        )

    def chokepoints(
        self,
        names: Sequence[str] = CHOKEPOINTS,
        *,
        force_synthetic: bool = False,
        refresh: bool = False,
    ) -> LoadResult:
        """Daily chokepoint transit counts (IMF PortWatch), about four years of history."""
        start = date.today() - timedelta(days=4 * 365)

        def fetch() -> tuple[pd.DataFrame, str]:
            frame = self._portwatch.fetch_chokepoints(names, start)
            return frame, self._portwatch.name

        return self._resolve(
            key="chokepoints-" + "-".join(names),
            provider="IMF PortWatch",
            fetch=fetch,
            synthetic=lambda: synthetic_chokepoints(names, start.isoformat()),
            force_synthetic=force_synthetic,
            refresh=refresh,
        )

    def macro(
        self,
        countries: Sequence[str] = WB_COUNTRIES,
        indicators: Sequence[str] = tuple(WB_INDICATORS),
        *,
        force_synthetic: bool = False,
        refresh: bool = False,
    ) -> LoadResult:
        """Annual World Bank indicators for the given countries."""
        end_year = date.today().year

        def fetch() -> tuple[pd.DataFrame, str]:
            frame = self._worldbank.fetch_indicators(countries, indicators, WB_START_YEAR, end_year)
            return frame, self._worldbank.name

        return self._resolve(
            key="macro-" + "-".join([*countries, *indicators]),
            provider="World Bank",
            fetch=fetch,
            synthetic=lambda: synthetic_worldbank(countries, indicators, WB_START_YEAR, end_year),
            force_synthetic=force_synthetic,
            refresh=refresh,
        )

    def write_snapshot(self, result: LoadResult) -> None:
        """Persist a real dataset as a committed-friendly snapshot (used by ``make snapshot``)."""
        if not result.is_real:
            raise ValueError("Refusing to snapshot synthetic data")
        self._snapshots.put(result.key, result.data, source=result.label)

    # ------------------------------------------------------------------ resolution chain

    def _resolve(self, *, key: str, **kwargs) -> LoadResult:
        """Run the fallback chain and stamp the result with its cache key."""
        return replace(self._resolve_chain(key=key, **kwargs), key=key)

    def _resolve_chain(
        self,
        *,
        key: str,
        provider: str,
        fetch: Callable[[], tuple[pd.DataFrame, str]],
        synthetic: Callable[[], pd.DataFrame],
        force_synthetic: bool,
        refresh: bool,
    ) -> LoadResult:
        if force_synthetic:
            return LoadResult(synthetic(), "synthetic", "Synthetic demo data", None, ("Demo mode",))

        notes: list[str] = []
        cached = self._cache.get(key)
        if cached is not None and cached.fresh and not refresh:
            return LoadResult(cached.data, "cache", cached.source, cached.fetched_at, ())

        if self._settings.offline:
            notes.append("Offline mode: network disabled")
        elif self._in_cooldown(provider):
            notes.append(f"{provider} skipped after a recent failure")
        else:
            try:
                data, label = fetch()
            except DataError as exc:
                self._start_cooldown(provider)
                notes.append(f"{provider} unavailable: {exc}")
                logger.warning("%s unavailable: %s", provider, exc)
            else:
                self._cache.put(key, data, source=label)
                return LoadResult(data, "live", label, datetime.now(UTC), tuple(notes))

        if cached is not None:
            notes.append("Serving stale cache")
            return LoadResult(
                cached.data, "stale-cache", cached.source, cached.fetched_at, tuple(notes)
            )

        snapshot = self._snapshots.get(key)
        if snapshot is not None:
            notes.append("Serving committed snapshot")
            return LoadResult(
                snapshot.data, "snapshot", snapshot.source, snapshot.fetched_at, tuple(notes)
            )

        notes.append("No real data available: showing synthetic demo data")
        return LoadResult(synthetic(), "synthetic", "Synthetic demo data", None, tuple(notes))

    def _in_cooldown(self, provider: str) -> bool:
        return self._monotonic() < self._cooldown_until.get(provider, 0.0)

    def _start_cooldown(self, provider: str) -> None:
        self._cooldown_until[provider] = self._monotonic() + self._settings.provider_cooldown_s
