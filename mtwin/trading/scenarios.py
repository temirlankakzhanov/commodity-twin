"""Stress scenarios for the trade network."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import pandas as pd

from mtwin.trading.network import Network
from mtwin.trading.optimizer import optimize_flows


@dataclass(frozen=True)
class Scenario:
    """A set of shocks applied on top of the base market state.

    Attributes:
        closed: chokepoints with zero capacity.
        capacity_multiplier: capacity scaling per chokepoint (1.0 = unchanged).
        freight_multiplier: scales every route's freight rate.
        insurance_add: extra USD/bbl (war-risk premium) per chokepoint, paid by each route using it.
        price_shock: relative benchmark price change, e.g. ``{"BRENT": 0.2}`` for +20 %.
    """

    name: str
    description: str = ""
    closed: tuple[str, ...] = ()
    capacity_multiplier: Mapping[str, float] = field(default_factory=dict)
    freight_multiplier: float = 1.0
    insurance_add: Mapping[str, float] = field(default_factory=dict)
    price_shock: Mapping[str, float] = field(default_factory=dict)

    def capacity_factor(self, chokepoint: str) -> float:
        """Multiplier applied to a chokepoint's base capacity (0 when closed)."""
        if chokepoint in self.closed:
            return 0.0
        return max(float(self.capacity_multiplier.get(chokepoint, 1.0)), 0.0)


BASE = Scenario("Base case", "Current prices, no disruption.")

PRESET_SCENARIOS: tuple[Scenario, ...] = (
    BASE,
    Scenario(
        "Red Sea closure",
        "Suez and Bab el-Mandeb closed; freight +25 %; war-risk premium on Hormuz.",
        closed=("Suez Canal", "Bab el-Mandeb Strait"),
        freight_multiplier=1.25,
        insurance_add={"Strait of Hormuz": 0.15},
    ),
    Scenario(
        "Hormuz disruption",
        "Hormuz capacity cut by 70 %; Brent +20 %; freight +40 %.",
        capacity_multiplier={"Strait of Hormuz": 0.3},
        freight_multiplier=1.4,
        insurance_add={"Strait of Hormuz": 0.40},
        price_shock={"BRENT": 0.20, "WTI": 0.20},
    ),
    Scenario(
        "Panama drought",
        "Panama Canal capacity cut by 60 % (no effect if no Panama route is optimal).",
        capacity_multiplier={"Panama Canal": 0.4},
    ),
    Scenario(
        "Price crash",
        "Brent -25 %, WTI -22 %. Margins of a same-benchmark book barely move; the risk sits in "
        "unhedged inventory (see the Risk tab).",
        price_shock={"BRENT": -0.25, "WTI": -0.22},
    ),
)


def run_scenarios(
    network: Network, prices: Mapping[str, float], scenarios: Sequence[Scenario] = PRESET_SCENARIOS
) -> pd.DataFrame:
    """Solve every scenario and tabulate total margin and change versus the base case."""
    rows = []
    base_margin: float | None = None
    for scenario in scenarios:
        plan = optimize_flows(network, prices, scenario)
        if base_margin is None:
            base_margin = plan.total_daily_margin_usd
        rows.append(
            {
                "scenario": scenario.name,
                "daily_margin_usd": plan.total_daily_margin_usd,
                "delta_vs_base_usd": plan.total_daily_margin_usd - base_margin,
                "volume_kbd": float(plan.flows["flow_kbd"].sum()),
                "status": plan.status,
            }
        )
    return pd.DataFrame(rows)


def scenario_from_signals(flags: pd.DataFrame, *, closure_share: float = 0.8) -> Scenario:
    """Build a scenario from the chokepoint monitor.

    Args:
        flags: output of ``mtwin.signals.chokepoints.latest_flags`` (columns ``chokepoint``,
            ``flagged``, ``pct_change``).
        closure_share: a flagged chokepoint is treated as closed when traffic is down by more
            than this fraction; otherwise capacity is scaled by the observed traffic ratio.
    """
    multipliers: dict[str, float] = {}
    closed: list[str] = []
    for row in flags.itertuples(index=False):
        if not row.flagged:
            continue
        ratio = max(1.0 + float(row.pct_change), 0.0)
        if ratio <= 1.0 - closure_share:
            closed.append(row.chokepoint)
        else:
            multipliers[row.chokepoint] = ratio
    names = ", ".join([*closed, *multipliers]) or "none"
    return Scenario(
        "Monitor-implied disruption",
        f"Chokepoints flagged by the traffic monitor: {names}.",
        closed=tuple(closed),
        capacity_multiplier=multipliers,
        freight_multiplier=1.15 if (closed or multipliers) else 1.0,
    )
