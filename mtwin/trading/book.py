"""Book exposures implied by a flow plan, and Monte Carlo margin-at-risk."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
import pandas as pd

from mtwin.trading.network import Network
from mtwin.trading.optimizer import KBD_TO_BBL, FlowPlan


def book_exposures(
    plan: FlowPlan,
    network: Network,
    prices: Mapping[str, float],
    hedge_ratio: float = 1.0,
) -> dict[str, float]:
    """Signed USD notional per benchmark for the cargoes in transit.

    Simplifying convention (documented in the methodology): inventory in transit is
    ``flow * transit_days`` barrels, valued at the origin price. The desk is **long the origin
    benchmark** and sells ``hedge_ratio`` of that notional **short in the destination
    benchmark**. With ``hedge_ratio = 1`` a Brent-to-Brent flow is perfectly hedged (zero net
    exposure) and a Houston-to-Rotterdam flow is a WTI-Brent spread; with ``0`` the inventory is
    completely unhedged.
    """
    if not 0.0 <= hedge_ratio <= 1.0:
        raise ValueError("hedge_ratio must be between 0 and 1")
    exposures: dict[str, float] = {}
    for row in plan.flows.itertuples(index=False):
        if row.flow_kbd <= 0:
            continue
        origin = network.origin(row.origin)
        dest = network.destination(row.destination)
        notional = row.flow_kbd * KBD_TO_BBL * row.transit_days * row.origin_price
        exposures[origin.benchmark] = exposures.get(origin.benchmark, 0.0) + notional
        exposures[dest.benchmark] = exposures.get(dest.benchmark, 0.0) - hedge_ratio * notional
    return {k: v for k, v in exposures.items() if abs(v) > 1e-6}


@dataclass(frozen=True)
class MarginAtRisk:
    """Distribution summary of the plan's daily margin after a price shock over ``horizon``."""

    base_margin_usd: float
    var_usd: float
    cvar_usd: float
    confidence: float
    horizon_days: int
    simulated: np.ndarray


def margin_at_risk(
    plan: FlowPlan,
    network: Network,
    prices: Mapping[str, float],
    returns: pd.DataFrame,
    *,
    horizon_days: int = 20,
    confidence: float = 0.95,
    n_sims: int = 5000,
    basis_vol_usd_bbl: float = 0.5,
    seed: int = 7,
) -> MarginAtRisk:
    """Bootstrap benchmark returns and re-price the *fixed* plan.

    Each simulation sums ``horizon_days`` randomly drawn daily log-return rows (joint draws
    keep the Brent-WTI correlation) and shocks all benchmark prices. Margin-at-risk is the
    shortfall of the confidence-quantile outcome versus the base margin.

    Flows between two ports priced off the *same* benchmark carry no flat-price risk, so each
    route also receives an independent normal shock to its differential/freight margin with
    standard deviation ``basis_vol_usd_bbl`` over the horizon. This is an assumption to be
    calibrated with desk data; set it to 0 to see flat-price risk only.
    """
    benchmarks = sorted(network.benchmarks)
    missing = [b for b in benchmarks if b not in returns.columns]
    if missing:
        raise KeyError(f"No return series for: {', '.join(missing)}")
    if not 0.5 < confidence < 1:
        raise ValueError("confidence must be in (0.5, 1)")
    sample = returns[benchmarks].dropna().to_numpy()
    if len(sample) < 100:
        raise ValueError("Need at least 100 return observations")

    rng = np.random.default_rng(seed)
    draws = rng.integers(0, len(sample), size=(n_sims, horizon_days))
    cumulative = sample[draws].sum(axis=1)  # (n_sims, n_benchmarks)
    factor = {b: np.exp(cumulative[:, i]) for i, b in enumerate(benchmarks)}

    active = plan.flows[plan.flows["flow_kbd"] > 0]
    margins = np.zeros(n_sims)
    for row in active.itertuples(index=False):
        origin = network.origin(row.origin)
        dest = network.destination(row.destination)
        o_price = prices[origin.benchmark] * factor[origin.benchmark] + origin.differential
        d_price = prices[dest.benchmark] * factor[dest.benchmark] + dest.differential
        fixed = row.freight + row.tolls + row.insurance + row.financing
        basis = rng.normal(0.0, basis_vol_usd_bbl, size=n_sims) if basis_vol_usd_bbl > 0 else 0.0
        margins += row.flow_kbd * KBD_TO_BBL * (d_price - o_price - fixed + basis)

    base = float(plan.total_daily_margin_usd)
    cut = np.quantile(margins, 1.0 - confidence)
    tail = margins[margins <= cut]
    return MarginAtRisk(
        base_margin_usd=base,
        var_usd=float(base - cut),
        cvar_usd=float(base - tail.mean()),
        confidence=confidence,
        horizon_days=horizon_days,
        simulated=margins,
    )
