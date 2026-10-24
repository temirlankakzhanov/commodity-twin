"""Framework-free computations behind the UI (testable without Streamlit)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import pandas as pd

from mtwin.data.service import CHOKEPOINTS, DataService, LoadResult
from mtwin.risk import ForecastConfig, ValidationResult, run_validation
from mtwin.risk.returns import log_returns, pnl_from_exposures
from mtwin.signals.chokepoints import compute_signals, latest_flags

BENCHMARKS = ("BRENT", "WTI")


@dataclass(frozen=True)
class MarketData:
    """Everything the app needs from the data layer, with provenance."""

    prices: LoadResult
    chokepoints: LoadResult
    macro: LoadResult

    @property
    def all_real(self) -> bool:
        """True when every dataset came from a real source (live, cache or snapshot)."""
        return all(r.is_real for r in (self.prices, self.chokepoints, self.macro))

    @property
    def any_synthetic(self) -> bool:
        """True when at least one dataset is synthetic."""
        return any(not r.is_real for r in (self.prices, self.chokepoints, self.macro))


def load_market(service: DataService, *, demo: bool = False, refresh: bool = False) -> MarketData:
    """Load prices, chokepoint traffic and macro indicators through the fallback chain."""
    return MarketData(
        prices=service.prices(force_synthetic=demo, refresh=refresh),
        chokepoints=service.chokepoints(force_synthetic=demo, refresh=refresh),
        macro=service.macro(force_synthetic=demo, refresh=refresh),
    )


def latest_prices(prices: pd.DataFrame) -> dict[str, float]:
    """Most recent price per benchmark used by the trade network."""
    last = prices.dropna().iloc[-1]
    return {name: float(last[name]) for name in BENCHMARKS}


def as_of(prices: pd.DataFrame) -> str:
    """Date of the latest complete price row, as text."""
    return str(prices.dropna().index[-1])[:10]


def book_pnl(exposures: Mapping[str, float], prices: pd.DataFrame) -> pd.Series:
    """Historical daily P&L of a book on the loaded price history."""
    return pnl_from_exposures(exposures, log_returns(prices))


def validate_book(
    exposures: Mapping[str, float],
    prices: pd.DataFrame,
    models: Sequence[str],
    cfg: ForecastConfig,
) -> ValidationResult:
    """Run the validation lab on the P&L of ``exposures``."""
    pnl = book_pnl(exposures, prices)
    if not float(pnl.abs().sum()):
        raise ValueError("The book has no exposure: enter at least one non-zero notional")
    return run_validation(pnl, models, cfg)


def monitor(
    transits: pd.DataFrame, names: Sequence[str] = CHOKEPOINTS
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Chokepoint signals (full history) and the latest flag per chokepoint."""
    subset = transits[transits["portname"].isin(names)]
    signals = compute_signals(subset)
    return signals, latest_flags(signals)
