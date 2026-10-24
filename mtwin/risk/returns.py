"""Returns and book P&L construction."""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd


def log_returns(prices: pd.DataFrame) -> pd.DataFrame:
    """Daily log returns. Prices must be strictly positive (see ``clean_prices``)."""
    if (prices <= 0).any().any():
        raise ValueError("Prices must be strictly positive to compute log returns")
    return np.log(prices).diff().dropna(how="all")


def pnl_from_exposures(exposures: Mapping[str, float], returns: pd.DataFrame) -> pd.Series:
    """Daily USD P&L of a book with signed USD notional per risk factor.

    ``P&L_t = sum_k notional_k * (exp(r_{k,t}) - 1)`` where ``r`` is the log return.
    A positive notional is a long position.

    Raises:
        KeyError: if an exposure refers to a factor that is not in ``returns``.
    """
    factors = [name for name, notional in exposures.items() if notional != 0.0]
    missing = [name for name in factors if name not in returns.columns]
    if missing:
        raise KeyError(f"No return series for factors: {', '.join(missing)}")
    if not factors:
        return pd.Series(0.0, index=returns.index, name="pnl_usd")
    notionals = pd.Series({name: float(exposures[name]) for name in factors})
    simple = np.expm1(returns[factors])
    return simple.mul(notionals, axis=1).sum(axis=1).rename("pnl_usd")
