"""Network, optimiser, scenarios, book exposures and the chokepoint monitor."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from mtwin.data.synthetic import synthetic_chokepoints
from mtwin.signals.chokepoints import compute_signals, latest_flags
from mtwin.trading import (
    BASE,
    Destination,
    Network,
    Origin,
    Route,
    Scenario,
    book_exposures,
    default_network,
    margin_at_risk,
    optimize_flows,
    route_economics,
    run_scenarios,
)
from mtwin.trading.scenarios import scenario_from_signals

PRICES = {"BRENT": 80.0, "WTI": 76.0}


@pytest.fixture
def tiny() -> Network:
    """Two routes from one origin to one destination: a cheap one via a chokepoint, a dear one not."""
    return Network(
        origins=(Origin("A", "BRENT", 0.0, 100.0),),
        destinations=(Destination("B", "BRENT", 5.0, 80.0),),
        routes=(
            Route("short", "A", "B", ("Choke",), freight=1.0, transit_days=0),
            Route("long", "A", "B", (), freight=3.0, transit_days=0),
        ),
        chokepoint_capacity_kbd={"Choke": 50.0},
        base_insurance=0.0,
        financing_rate=0.0,
    )


def test_route_economics_arithmetic(tiny):
    econ = route_economics(tiny, PRICES).set_index("route")
    assert econ.loc["short", "margin_usd_bbl"] == pytest.approx(5.0 - 1.0)
    assert econ.loc["long", "margin_usd_bbl"] == pytest.approx(5.0 - 3.0)


def test_route_economics_missing_price(tiny):
    with pytest.raises(KeyError):
        route_economics(tiny, {"WTI": 70.0})


def test_optimizer_fills_cheap_route_then_spills_over(tiny):
    plan = optimize_flows(tiny, PRICES)
    flows = plan.flows.set_index("route")["flow_kbd"]
    assert plan.status == "optimal"
    assert flows["short"] == pytest.approx(50.0)  # chokepoint capacity
    assert flows["long"] == pytest.approx(30.0)  # remaining demand
    assert plan.total_daily_margin_usd == pytest.approx((50 * 4 + 30 * 2) * 1000)


def test_shadow_prices_equal_marginal_value(tiny):
    plan = optimize_flows(tiny, PRICES)
    shadow = plan.shadow_prices.set_index(["constraint", "name"])["shadow_usd_bbl"]
    assert shadow[("chokepoint", "Choke")] == pytest.approx(2.0)  # 4 - 2 USD/bbl
    assert shadow[("demand", "B")] == pytest.approx(2.0)
    assert shadow[("supply", "A")] == pytest.approx(0.0)


def test_shadow_price_predicts_objective_change(tiny):
    base = optimize_flows(tiny, PRICES)
    bumped = Network(tiny.origins, tiny.destinations, tiny.routes, {"Choke": 51.0}, 0.0, 0.0)
    delta = optimize_flows(bumped, PRICES).total_daily_margin_usd - base.total_daily_margin_usd
    assert delta == pytest.approx(2.0 * 1000)


def test_closed_chokepoint_forces_detour_and_lowers_margin(tiny):
    closed = Scenario("closed", closed=("Choke",))
    plan = optimize_flows(tiny, PRICES, closed)
    flows = plan.flows.set_index("route")["flow_kbd"]
    assert flows["short"] == 0.0
    assert flows["long"] == pytest.approx(80.0)
    assert plan.total_daily_margin_usd < optimize_flows(tiny, PRICES).total_daily_margin_usd


def test_negative_margin_routes_are_not_used(tiny):
    plan = optimize_flows(tiny, PRICES, Scenario("freight", freight_multiplier=10.0))
    assert plan.flows["flow_kbd"].sum() == 0.0
    assert plan.total_daily_margin_usd == 0.0


def test_scenario_shocks_move_prices_and_costs(tiny):
    shocked = route_economics(
        tiny, PRICES, Scenario("s", price_shock={"BRENT": 0.5}, insurance_add={"Choke": 0.7})
    ).set_index("route")
    # origin 120, destination 125 after a 50 % shock: spread 5 on both routes
    assert shocked.loc["short", "destination_price"] == pytest.approx(125.0)
    assert shocked.loc["short", "insurance"] == pytest.approx(0.7)
    assert shocked.loc["long", "insurance"] == pytest.approx(0.0)


def test_network_validation():
    with pytest.raises(ValueError, match="unknown origin"):
        Network(
            (Origin("A", "BRENT", 0, 1),),
            (Destination("B", "BRENT", 0, 1),),
            (Route("r", "X", "B", (), 1, 1),),
            {},
        )
    with pytest.raises(ValueError, match="without capacity"):
        Network(
            (Origin("A", "BRENT", 0, 1),),
            (Destination("B", "BRENT", 0, 1),),
            (Route("r", "A", "B", ("Nowhere",), 1, 1),),
            {},
        )


def test_default_network_scenarios_are_ordered_sensibly():
    network = default_network()
    table = run_scenarios(network, PRICES).set_index("scenario")
    assert table.loc["Base case", "delta_vs_base_usd"] == 0.0
    assert (
        table.loc["Red Sea closure", "daily_margin_usd"]
        < table.loc["Base case", "daily_margin_usd"]
    )
    assert (
        table.loc["Hormuz disruption", "daily_margin_usd"]
        < table.loc["Base case", "daily_margin_usd"]
    )
    assert (table["status"] == "optimal").all()


def test_supply_and_demand_limits_are_respected():
    network = default_network()
    plan = optimize_flows(network, {"BRENT": 85.0, "WTI": 70.0})
    flows = plan.flows
    for origin in network.origins:
        assert (
            flows.loc[flows["origin"] == origin.name, "flow_kbd"].sum() <= origin.supply_kbd + 1e-6
        )
    for dest in network.destinations:
        assert (
            flows.loc[flows["destination"] == dest.name, "flow_kbd"].sum() <= dest.demand_kbd + 1e-6
        )


def test_book_exposures_hedge_ratio():
    network = default_network()
    prices = {"BRENT": 85.0, "WTI": 70.0}  # wide WTI discount: Houston flows appear
    plan = optimize_flows(network, prices)
    assert plan.flows.loc[plan.flows["origin"] == "Houston", "flow_kbd"].sum() > 0
    unhedged = book_exposures(plan, network, prices, hedge_ratio=0.0)
    hedged = book_exposures(plan, network, prices, hedge_ratio=1.0)
    assert unhedged["WTI"] > 0 and unhedged["BRENT"] > 0
    assert hedged["WTI"] > 0 > hedged["BRENT"]
    assert sum(unhedged.values()) > sum(hedged.values())
    with pytest.raises(ValueError):
        book_exposures(plan, network, prices, hedge_ratio=1.5)


def test_margin_at_risk_is_positive_deterministic_and_respects_basis_vol(returns):
    network = default_network()
    plan = optimize_flows(network, PRICES)
    a = margin_at_risk(plan, network, PRICES, returns, n_sims=2000)
    b = margin_at_risk(plan, network, PRICES, returns, n_sims=2000)
    assert a.var_usd > 0 and a.cvar_usd >= a.var_usd
    assert a.var_usd == b.var_usd
    flat = margin_at_risk(plan, network, PRICES, returns, n_sims=2000, basis_vol_usd_bbl=0.0)
    assert flat.simulated.std() < a.simulated.std()
    with pytest.raises(ValueError):
        margin_at_risk(plan, network, PRICES, returns, confidence=0.3)


# ------------------------------------------------------------------ chokepoint monitor


def _transits(disrupted: bool) -> pd.DataFrame:
    frame = synthetic_chokepoints(["Suez Canal", "Strait of Hormuz"], end="2025-12-31")
    if not disrupted:
        rng = np.random.default_rng(0)
        mask = frame["portname"] == "Suez Canal"
        frame.loc[mask, "n_total"] = rng.poisson(45, mask.sum())
    return frame


def test_monitor_flags_the_disrupted_chokepoint_only():
    flags = latest_flags(compute_signals(_transits(disrupted=True))).set_index("chokepoint")
    assert bool(flags.loc["Suez Canal", "flagged"]) is True
    assert bool(flags.loc["Strait of Hormuz", "flagged"]) is False
    assert flags.loc["Suez Canal", "pct_change"] < -0.25


def test_monitor_is_quiet_without_disruption():
    signals = compute_signals(_transits(disrupted=False))
    assert not signals["flagged"].any()


def test_monitor_requires_columns():
    with pytest.raises(ValueError):
        compute_signals(pd.DataFrame({"date": [], "x": []}))


def test_scenario_from_signals_closes_or_scales():
    flags = pd.DataFrame(
        {
            "chokepoint": ["Suez Canal", "Strait of Hormuz", "Panama Canal"],
            "flagged": [True, True, False],
            "pct_change": [-0.9, -0.4, -0.5],
        }
    )
    scenario = scenario_from_signals(flags)
    assert scenario.closed == ("Suez Canal",)
    assert scenario.capacity_multiplier == {"Strait of Hormuz": pytest.approx(0.6)}
    assert scenario.capacity_factor("Panama Canal") == 1.0
    assert scenario_from_signals(flags.assign(flagged=False)).freight_multiplier == 1.0


def test_base_scenario_is_neutral():
    assert BASE.capacity_factor("Anything") == 1.0
