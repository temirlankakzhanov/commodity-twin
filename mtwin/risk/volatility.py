"""Conditional-volatility filters: EWMA (RiskMetrics) and GARCH(1,1).

Both functions return **one-step-ahead** volatility forecasts: ``sigma[t]`` depends only on
observations up to ``t - 1``. This is what makes the downstream backtests free of look-ahead.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.signal import lfilter

MIN_VARIANCE = 1e-18


def _filter_variance(
    x2: np.ndarray, beta: float, omega: float, alpha: float, v0: float
) -> np.ndarray:
    """Solve ``v[t] = omega + alpha * x2[t-1] + beta * v[t-1]`` with ``v[0] = v0``."""
    drive = np.empty_like(x2)
    drive[0] = v0
    drive[1:] = omega + alpha * x2[:-1]
    return lfilter([1.0], [1.0, -beta], drive)


def ewma_sigma(x: pd.Series, lam: float = 0.94, seed_window: int = 30) -> pd.Series:
    """RiskMetrics EWMA volatility forecast (zero-mean).

    ``v[t] = lam * v[t-1] + (1 - lam) * x[t-1]**2``. The recursion is seeded with the mean
    square of the first ``seed_window`` observations, so the first ``seed_window`` forecasts
    are not out-of-sample; backtests start well after that warm-up.
    """
    if not 0.0 < lam < 1.0:
        raise ValueError("lam must be in (0, 1)")
    values = x.to_numpy(dtype=float)
    if len(values) <= seed_window:
        raise ValueError("Series is shorter than the seed window")
    x2 = values**2
    seed = float(np.mean(x2[:seed_window]))
    variance = _filter_variance(x2, beta=lam, omega=0.0, alpha=1.0 - lam, v0=seed)
    return pd.Series(np.sqrt(np.maximum(variance, MIN_VARIANCE)), index=x.index, name="sigma")


@dataclass(frozen=True)
class Garch11Params:
    """GARCH(1,1) parameters: ``v[t] = omega + alpha * x[t-1]^2 + beta * v[t-1]``."""

    omega: float
    alpha: float
    beta: float
    long_run_variance: float

    @property
    def persistence(self) -> float:
        """``alpha + beta``; values close to 1 mean shocks to volatility die out slowly."""
        return self.alpha + self.beta


def fit_garch11(x: pd.Series | np.ndarray) -> Garch11Params:
    """Gaussian quasi-maximum-likelihood fit of a zero-mean GARCH(1,1) with variance targeting.

    ``omega = (1 - alpha - beta) * sample_variance`` so only ``alpha`` and ``beta`` are
    estimated, subject to ``alpha, beta >= 0`` and ``alpha + beta < 1``.
    """
    values = np.asarray(x, dtype=float)
    if len(values) < 250:
        raise ValueError("At least 250 observations are needed to fit GARCH(1,1)")
    x2 = values**2
    long_run = float(np.mean(x2))

    def nll(theta: np.ndarray) -> float:
        alpha, beta = theta
        omega = long_run * (1.0 - alpha - beta)
        variance = np.maximum(_filter_variance(x2, beta, omega, alpha, long_run), MIN_VARIANCE)
        return float(0.5 * np.sum(np.log(variance) + x2 / variance))

    best = None
    for start in ((0.05, 0.90), (0.10, 0.80), (0.03, 0.95)):
        result = minimize(
            nll,
            x0=np.array(start),
            method="SLSQP",
            bounds=[(1e-4, 0.5), (0.2, 0.9995)],
            constraints=[{"type": "ineq", "fun": lambda t: 0.9999 - t[0] - t[1]}],
        )
        if result.success and (best is None or result.fun < best.fun):
            best = result
    if best is None:
        raise ValueError("GARCH(1,1) optimisation did not converge")
    alpha, beta = (float(v) for v in best.x)
    return Garch11Params(long_run * (1.0 - alpha - beta), alpha, beta, long_run)


def garch11_sigma(x: pd.Series, params: Garch11Params) -> pd.Series:
    """One-step-ahead GARCH(1,1) volatility with *fixed* parameters (no re-estimation)."""
    x2 = x.to_numpy(dtype=float) ** 2
    variance = _filter_variance(
        x2, params.beta, params.omega, params.alpha, params.long_run_variance
    )
    return pd.Series(np.sqrt(np.maximum(variance, MIN_VARIANCE)), index=x.index, name="sigma")
