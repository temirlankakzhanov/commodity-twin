"""Deterministic synthetic data used as the last-resort fallback and in tests.

Everything produced here is **synthetic**: it imitates the statistical shape of the real
series (volatility clustering, fat tails, correlated crude benchmarks, a disruption episode)
but is not market data. The UI always labels it as such.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd

BASELINE_TRANSITS = {
    "Suez Canal": 45,
    "Bab el-Mandeb Strait": 70,
    "Strait of Hormuz": 95,
    "Panama Canal": 36,
    "Malacca Strait": 280,
    "Cape of Good Hope": 110,
}
DISRUPTED = ("Suez Canal", "Bab el-Mandeb Strait")


def _garch_returns(
    rng: np.random.Generator,
    n: int,
    annual_vol: float,
    alpha: float = 0.08,
    beta: float = 0.90,
    df: float = 6.0,
    stress: tuple[int, int, float] | None = None,
) -> np.ndarray:
    """Simulate GARCH(1,1) log returns with Student-t innovations."""
    long_run = (annual_vol / np.sqrt(252.0)) ** 2
    omega = long_run * (1.0 - alpha - beta)
    eps = rng.standard_t(df, size=n) / np.sqrt(df / (df - 2.0))
    scale = np.ones(n)
    if stress is not None:
        lo, hi, mult = stress
        scale[lo:hi] = mult  # exogenous volatility burst; it does not feed the GARCH recursion
    out = np.empty(n)
    var = long_run
    for t in range(n):
        shock = np.sqrt(var) * eps[t]
        out[t] = shock * scale[t]
        var = omega + alpha * shock**2 + beta * var
    return out


def _mean_reverting_prices(returns: np.ndarray, target: float, kappa: float) -> np.ndarray:
    """Price path whose log level is pulled gently towards ``target`` (keeps levels plausible)."""
    log_target = np.log(target)
    log_price = np.empty(len(returns))
    previous = log_target
    for t, r in enumerate(returns):
        previous = previous + r - kappa * (previous - log_target)
        log_price[t] = previous
    return np.exp(log_price)


def synthetic_prices(
    start: str = "2010-01-01", end: str | None = None, seed: int = 7
) -> pd.DataFrame:
    """Daily BRENT, WTI and HENRY_HUB prices (USD) on business days."""
    end_ts = pd.Timestamp(end) if end else pd.Timestamp.today().normalize()
    dates = pd.bdate_range(start, end_ts, name="date")
    n = len(dates)
    rng = np.random.default_rng(seed)
    stress = (int(n * 0.70), int(n * 0.70) + 40, 2.5)
    brent_r = _garch_returns(rng, n, annual_vol=0.33, stress=stress)
    wti_r = 0.93 * brent_r + rng.normal(0.0, 0.006, size=n)
    gas_r = _garch_returns(rng, n, annual_vol=0.55, alpha=0.06, beta=0.92)
    return pd.DataFrame(
        {
            "BRENT": _mean_reverting_prices(brent_r, target=75.0, kappa=0.003),
            "WTI": _mean_reverting_prices(wti_r, target=71.0, kappa=0.003),
            "HENRY_HUB": _mean_reverting_prices(gas_r, target=3.5, kappa=0.005),
        },
        index=dates,
    )


def synthetic_chokepoints(
    names: Sequence[str],
    start: str | None = None,
    end: str | None = None,
    seed: int = 11,
) -> pd.DataFrame:
    """Daily transit counts per chokepoint, with a disruption in the last 45 days."""
    end_ts = pd.Timestamp(end) if end else pd.Timestamp.today().normalize()
    start_ts = pd.Timestamp(start) if start else end_ts - pd.Timedelta(days=4 * 365)
    dates = pd.date_range(start_ts, end_ts, name="date")
    rng = np.random.default_rng(seed)
    frames = []
    for name in names:
        base = BASELINE_TRANSITS.get(name, 60)
        seasonal = 1.0 + 0.05 * np.sin(2 * np.pi * dates.day_of_year / 365.0)
        weekend = np.where(dates.day_of_week >= 5, 0.92, 1.0)
        level = base * seasonal * weekend
        if name in DISRUPTED:
            level = np.where(dates > end_ts - pd.Timedelta(days=45), level * 0.45, level)
        total = rng.poisson(level)
        tanker = rng.binomial(total, 0.35)
        frames.append(
            pd.DataFrame(
                {
                    "date": dates,
                    "portid": f"synthetic-{name}",
                    "portname": name,
                    "n_tanker": tanker,
                    "n_total": total,
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


def synthetic_worldbank(
    countries: Sequence[str], indicators: Sequence[str], start_year: int, end_year: int
) -> pd.DataFrame:
    """Annual indicator values on plausible scales (synthetic)."""
    scale = {"NE.TRD.GNFS.ZS": (60.0, 12.0), "NY.GDP.MKTP.CD": (1.5e12, 4.0e11)}
    rows = []
    for i, country in enumerate(countries):
        for j, indicator in enumerate(indicators):
            rng = np.random.default_rng(100 + 10 * i + j)
            mean, spread = scale.get(indicator, (50.0, 10.0))
            level = mean * (0.6 + 0.8 * rng.random())
            for year in range(start_year, end_year + 1):
                level *= 1.0 + rng.normal(0.01, spread / mean * 0.15)
                rows.append(
                    {
                        "country_iso3": country,
                        "country": country,
                        "indicator": indicator,
                        "year": year,
                        "value": float(level),
                    }
                )
    return pd.DataFrame(rows)
