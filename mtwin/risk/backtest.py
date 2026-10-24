"""Backtests for VaR and ES forecasts.

Implemented tests:

* Kupiec (1995) proportion-of-failures test, unconditional coverage.
* Christoffersen (1998) independence test and the joint conditional-coverage test.
* Basel traffic-light zones, derived from binomial cumulative probabilities.
* Acerbi-Szekely (2014) Z2 statistic for Expected Shortfall (statistic only, no p-value).

All functions take **positive** losses and VaR/ES numbers, with exceptions defined as
``loss > VaR``.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.special import xlogy
from scipy.stats import binom, chi2

GREEN_LIMIT = 0.95
YELLOW_LIMIT = 0.9999


@dataclass(frozen=True)
class TestResult:
    """Outcome of a likelihood-ratio test."""

    __test__ = False  # not a pytest test class

    statistic: float
    pvalue: float
    df: int

    def rejects(self, level: float = 0.05) -> bool:
        """True when the null hypothesis is rejected at ``level``."""
        return self.pvalue < level


def exceptions(losses: np.ndarray, var: np.ndarray) -> np.ndarray:
    """Boolean hit sequence: ``loss > VaR``."""
    return np.asarray(losses) > np.asarray(var)


def kupiec_pof(n_obs: int, n_exc: int, p: float) -> TestResult:
    """Kupiec proportion-of-failures test.

    H0: the true exception probability equals ``p`` (``p = 1 - confidence``).
    The statistic is asymptotically chi-squared with one degree of freedom.
    """
    if not 0 < p < 1:
        raise ValueError("p must be in (0, 1)")
    if not 0 <= n_exc <= n_obs or n_obs <= 0:
        raise ValueError("Need 0 <= n_exc <= n_obs and n_obs > 0")
    log_l0 = xlogy(n_obs - n_exc, 1.0 - p) + xlogy(n_exc, p)
    phat = n_exc / n_obs
    log_l1 = xlogy(n_obs - n_exc, 1.0 - phat) + xlogy(n_exc, phat)
    stat = float(max(-2.0 * (log_l0 - log_l1), 0.0))
    return TestResult(stat, float(chi2.sf(stat, 1)), 1)


def christoffersen_independence(hits: np.ndarray) -> TestResult:
    """Christoffersen independence test on the exception sequence.

    H0: exceptions are serially independent (no clustering). Uses first-order Markov
    transition counts; chi-squared with one degree of freedom.
    """
    h = np.asarray(hits, dtype=int)
    if len(h) < 2:
        raise ValueError("Need at least two observations")
    prev, curr = h[:-1], h[1:]
    n00 = int(np.sum((prev == 0) & (curr == 0)))
    n01 = int(np.sum((prev == 0) & (curr == 1)))
    n10 = int(np.sum((prev == 1) & (curr == 0)))
    n11 = int(np.sum((prev == 1) & (curr == 1)))
    total = n00 + n01 + n10 + n11
    pi = (n01 + n11) / total
    pi01 = n01 / (n00 + n01) if (n00 + n01) else 0.0
    pi11 = n11 / (n10 + n11) if (n10 + n11) else 0.0
    log_l0 = xlogy(n00 + n10, 1.0 - pi) + xlogy(n01 + n11, pi)
    log_l1 = xlogy(n00, 1.0 - pi01) + xlogy(n01, pi01) + xlogy(n10, 1.0 - pi11) + xlogy(n11, pi11)
    stat = float(max(-2.0 * (log_l0 - log_l1), 0.0))
    return TestResult(stat, float(chi2.sf(stat, 1)), 1)


def conditional_coverage(hits: np.ndarray, p: float) -> TestResult:
    """Joint test of correct coverage and independence (chi-squared, two degrees of freedom)."""
    h = np.asarray(hits, dtype=int)
    pof = kupiec_pof(len(h), int(h.sum()), p)
    ind = christoffersen_independence(h)
    stat = pof.statistic + ind.statistic
    return TestResult(stat, float(chi2.sf(stat, 2)), 2)


def basel_traffic_light(n_exc: int, n_obs: int, p: float = 0.01) -> str:
    """Basel zone for ``n_exc`` exceptions in ``n_obs`` days.

    Zones follow the cumulative binomial probability of observing at most ``n_exc``
    exceptions under a correct model: green below 95 %, yellow below 99.99 %, red above.
    For 250 days and ``p = 0.01`` this reproduces the regulatory 0-4 / 5-9 / 10+ zones.
    """
    cumulative = float(binom.cdf(n_exc, n_obs, p))
    if cumulative < GREEN_LIMIT:
        return "green"
    if cumulative < YELLOW_LIMIT:
        return "yellow"
    return "red"


def es_z2(losses: np.ndarray, var: np.ndarray, es: np.ndarray, alpha: float) -> float:
    """Acerbi-Szekely Z2 statistic.

    ``Z2 = sum_t [L_t * 1(L_t > VaR_t) / ES_t] / (T * (1 - alpha)) - 1``.
    Its expectation is zero for a correct model; **positive values mean ES is too low**.
    No p-value is reported because it requires Monte Carlo simulation under the model.
    """
    losses, var, es = (np.asarray(a, dtype=float) for a in (losses, var, es))
    hit = losses > var
    safe_es = np.where(es > 0, es, np.nan)
    ratio = np.where(hit, losses / safe_es, 0.0)
    return float(np.nansum(ratio) / (len(losses) * (1.0 - alpha)) - 1.0)
