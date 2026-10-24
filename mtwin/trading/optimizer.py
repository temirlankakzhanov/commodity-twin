"""Linear-programming flow optimiser.

Decision variable: flow ``x_r`` (kb/d) on each route. Objective: maximise
``sum_r margin_r * x_r`` subject to origin supply, destination demand and chokepoint capacity.
Shadow prices (the dual values) say how much one more kb/d of each constraint's right-hand
side would add to the objective, in USD per barrel.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
from scipy.optimize import linprog

from mtwin.trading.network import Network

if TYPE_CHECKING:
    from mtwin.trading.scenarios import Scenario

KBD_TO_BBL = 1000.0


@dataclass(frozen=True)
class FlowPlan:
    """Optimal flows, objective value and shadow prices."""

    flows: pd.DataFrame
    total_daily_margin_usd: float
    shadow_prices: pd.DataFrame
    status: str


def _shocked_prices(prices: Mapping[str, float], scenario: Scenario | None) -> dict[str, float]:
    shock = scenario.price_shock if scenario else {}
    return {k: float(v) * (1.0 + float(shock.get(k, 0.0))) for k, v in prices.items()}


def route_economics(
    network: Network, prices: Mapping[str, float], scenario: Scenario | None = None
) -> pd.DataFrame:
    """Unit economics of every route under a scenario (USD per barrel).

    ``margin = destination price - origin price - freight - tolls - insurance - financing``.
    """
    missing = network.benchmarks - set(prices)
    if missing:
        raise KeyError(f"Missing benchmark prices: {', '.join(sorted(missing))}")
    shocked = _shocked_prices(prices, scenario)
    freight_mult = scenario.freight_multiplier if scenario else 1.0
    war_risk = dict(scenario.insurance_add) if scenario else {}
    rows = []
    for route in network.routes:
        origin = network.origin(route.origin)
        dest = network.destination(route.destination)
        origin_price = shocked[origin.benchmark] + origin.differential
        dest_price = shocked[dest.benchmark] + dest.differential
        freight = route.freight * freight_mult
        insurance = network.base_insurance + sum(war_risk.get(c, 0.0) for c in route.chokepoints)
        financing = origin_price * network.financing_rate * route.transit_days / 365.0
        margin = dest_price - origin_price - freight - route.tolls - insurance - financing
        rows.append(
            {
                "route": route.name,
                "origin": route.origin,
                "destination": route.destination,
                "chokepoints": ", ".join(route.chokepoints) or "-",
                "origin_price": origin_price,
                "destination_price": dest_price,
                "freight": freight,
                "tolls": route.tolls,
                "insurance": insurance,
                "financing": financing,
                "margin_usd_bbl": margin,
                "transit_days": route.transit_days,
            }
        )
    return pd.DataFrame(rows)


def optimize_flows(
    network: Network, prices: Mapping[str, float], scenario: Scenario | None = None
) -> FlowPlan:
    """Solve for the margin-maximising flows (HiGHS via ``scipy.optimize.linprog``)."""
    econ = route_economics(network, prices, scenario)
    routes = network.routes
    n = len(routes)
    margin = econ["margin_usd_bbl"].to_numpy()

    rows: list[np.ndarray] = []
    rhs: list[float] = []
    labels: list[tuple[str, str]] = []
    for origin in network.origins:
        rows.append(np.array([1.0 if r.origin == origin.name else 0.0 for r in routes]))
        rhs.append(origin.supply_kbd)
        labels.append(("supply", origin.name))
    for dest in network.destinations:
        rows.append(np.array([1.0 if r.destination == dest.name else 0.0 for r in routes]))
        rhs.append(dest.demand_kbd)
        labels.append(("demand", dest.name))
    for name, capacity in network.chokepoint_capacity_kbd.items():
        factor = scenario.capacity_factor(name) if scenario else 1.0
        rows.append(np.array([1.0 if name in r.chokepoints else 0.0 for r in routes]))
        rhs.append(capacity * factor)
        labels.append(("chokepoint", name))

    result = linprog(
        c=-margin,
        A_ub=np.vstack(rows),
        b_ub=np.array(rhs),
        bounds=[(0.0, None)] * n,
        method="highs",
    )
    if not result.success:
        return FlowPlan(
            flows=econ.assign(flow_kbd=0.0, daily_margin_usd=0.0),
            total_daily_margin_usd=0.0,
            shadow_prices=pd.DataFrame(
                columns=["constraint", "name", "limit_kbd", "shadow_usd_bbl", "binding"]
            ),
            status=f"failed: {result.message}",
        )

    flow = np.clip(result.x, 0.0, None)
    flow[flow < 1e-6] = 0.0
    flows = econ.assign(flow_kbd=flow, daily_margin_usd=flow * margin * KBD_TO_BBL)
    shadow = -np.asarray(result.ineqlin.marginals)
    shadow_table = pd.DataFrame(
        {
            "constraint": [kind for kind, _ in labels],
            "name": [name for _, name in labels],
            "limit_kbd": rhs,
            "shadow_usd_bbl": np.where(np.abs(shadow) < 1e-9, 0.0, shadow),
            "binding": np.asarray(result.ineqlin.residual) < 1e-6,
        }
    )
    return FlowPlan(flows, float(-result.fun * KBD_TO_BBL), shadow_table, "optimal")
