"""Value-at-Risk and Expected Shortfall forecasters.

Conventions used throughout the package:

* The input series ``x`` is a P&L or return series (positive = gain).
* Losses are ``-x``. VaR and ES are reported as **positive** loss numbers.
* A forecast stamped ``t`` is made with information up to ``t - 1`` only.
* Every model forecasts the same dates (from ``max(window, garch_train)`` onwards) so results
  are directly comparable. GARCH parameters are estimated once on the first
  ``garch_train`` observations and then frozen, which keeps the test period out-of-sample.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view
from scipy.stats import norm

from mtwin.risk.volatility import ewma_sigma, fit_garch11, garch11_sigma

MODEL_LABELS = {
    "historical": "Historical simulation",
    "normal": "Normal (rolling sigma)",
    "normal_ewma": "Normal (EWMA sigma)",
    "fhs_ewma": "Filtered HS (EWMA)",
    "fhs_garch": "Filtered HS (GARCH(1,1))",
}
MIN_TEST_OBS = 100


@dataclass(frozen=True)
class ForecastConfig:
    """Settings shared by all models."""

    alpha: float = 0.99
    window: int = 500
    lam: float = 0.94
    garch_train: int = 750

    def __post_init__(self) -> None:
        if not 0.5 < self.alpha < 1.0:
            raise ValueError("alpha must be in (0.5, 1)")
        if self.window < 100:
            raise ValueError("window must be at least 100 observations")

    @property
    def start(self) -> int:
        """Index of the first forecast date."""
        return max(self.window, self.garch_train)


def _tail_stats(windows: np.ndarray, alpha: float) -> tuple[np.ndarray, np.ndarray]:
    """VaR and ES for every row of ``windows`` (rows hold loss samples)."""
    var = np.quantile(windows, alpha, axis=1)
    in_tail = windows >= var[:, None]
    es = np.where(in_tail, windows, 0.0).sum(axis=1) / in_tail.sum(axis=1)
    return var, es


def _trailing_windows(values: np.ndarray, window: int, start: int) -> np.ndarray:
    """Rows ``values[t-window:t]`` for ``t = start .. n-1``."""
    n = len(values)
    return sliding_window_view(values, window)[start - window : n - window]


def _normal_var_es(sigma: np.ndarray, alpha: float) -> tuple[np.ndarray, np.ndarray]:
    z = norm.ppf(alpha)
    return sigma * z, sigma * norm.pdf(z) / (1.0 - alpha)


def forecast_var_es(x: pd.Series, model: str, cfg: ForecastConfig) -> pd.DataFrame:
    """Rolling one-day VaR/ES forecasts.

    Returns:
        A frame indexed by forecast date with columns ``var``, ``es`` (positive losses) and
        ``loss`` (the realised loss ``-x_t``).

    Raises:
        ValueError: for an unknown model or when the sample is too short.
    """
    if model not in MODEL_LABELS:
        raise ValueError(f"Unknown model '{model}'. Choose from {sorted(MODEL_LABELS)}")
    values = x.to_numpy(dtype=float)
    n, start = len(values), cfg.start
    if n - start < MIN_TEST_OBS:
        raise ValueError(
            f"Need at least {start + MIN_TEST_OBS} observations for this configuration, got {n}"
        )
    losses = -values

    if model == "historical":
        var, es = _tail_stats(_trailing_windows(losses, cfg.window, start), cfg.alpha)
    elif model == "normal":
        windows = _trailing_windows(values**2, cfg.window, start)
        var, es = _normal_var_es(np.sqrt(windows.mean(axis=1)), cfg.alpha)
    else:
        if model == "fhs_garch":
            params = fit_garch11(values[: cfg.garch_train])
            sigma = garch11_sigma(x, params).to_numpy()
        else:
            sigma = ewma_sigma(x, cfg.lam).to_numpy()
        if model == "normal_ewma":
            var, es = _normal_var_es(sigma[start:], cfg.alpha)
        else:  # filtered historical simulation: scale standardised past losses by today's sigma
            standardised = losses / sigma
            q, tail_mean = _tail_stats(
                _trailing_windows(standardised, cfg.window, start), cfg.alpha
            )
            var, es = sigma[start:] * q, sigma[start:] * tail_mean

    return pd.DataFrame({"var": var, "es": es, "loss": losses[start:]}, index=x.index[start:])
