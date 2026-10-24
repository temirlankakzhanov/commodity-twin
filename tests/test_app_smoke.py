"""Run the whole page code against an in-memory Streamlit stand-in, plus chart tests."""

from __future__ import annotations

import importlib
import sys

import numpy as np
import pytest
from matplotlib.figure import Figure

from mtwin.data.synthetic import synthetic_chokepoints
from mtwin.risk import ForecastConfig, run_validation
from mtwin.risk.returns import pnl_from_exposures
from mtwin.signals.chokepoints import compute_signals
from mtwin.trading import (
    default_network,
    margin_at_risk,
    optimize_flows,
    route_economics,
    run_scenarios,
)
from mtwin.ui import charts
from mtwin.ui.compute import as_of, latest_prices, load_market, monitor, validate_book

from .fake_streamlit import make_streamlit

PRICES = {"BRENT": 80.0, "WTI": 76.0}


@pytest.fixture
def app(monkeypatch, tmp_path):
    """Import ``mtwin.ui.pages`` with a fake ``streamlit`` and an offline, empty data directory."""
    monkeypatch.setenv("MTWIN_OFFLINE", "1")
    monkeypatch.setenv("MTWIN_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("MTWIN_SNAPSHOT_DIR", str(tmp_path / "snap"))
    fake = make_streamlit()
    monkeypatch.setitem(sys.modules, "streamlit", fake)
    monkeypatch.delitem(sys.modules, "mtwin.ui.pages", raising=False)
    pages = importlib.import_module("mtwin.ui.pages")
    yield pages, fake
    sys.modules.pop("mtwin.ui.pages", None)


def test_full_page_renders_on_synthetic_fallback(app):
    pages, fake = app
    pages.run()
    rec = fake.recorder
    assert any("SYNTHETIC" in msg for msg in rec.of("warning"))
    assert not rec.of("error"), rec.of("error")
    labels = [label for label, _ in rec.of("metric")]
    assert "Base daily margin" in labels and "95% margin-at-risk (20d)" in labels
    assert len(rec.of("pyplot")) >= 6
    assert all(isinstance(fig, Figure) for fig in rec.of("pyplot"))
    memo = rec.of("download")[0][1]
    assert "Independent model validation memo" in memo
    assert rec.of("page_config")[0]["layout"] == "wide"


def test_usd_formatting(app):
    pages, _ = app
    assert pages.usd_m(1_234_567) == "$1.23M"
    assert pages.usd_m(-1_234_567) == "-$1.23M"


def test_compute_layer_end_to_end(settings, prices):
    from mtwin.data import DataService

    market = load_market(DataService(Settings_offline(settings)), demo=True)
    assert market.any_synthetic and not market.all_real
    last = latest_prices(market.prices.data)
    assert set(last) == {"BRENT", "WTI"} and as_of(market.prices.data)
    signals, flags = monitor(market.chokepoints.data)
    assert not signals.empty and "Suez Canal" in set(flags["chokepoint"])
    result = validate_book({"BRENT": 10e6}, market.prices.data, ["fhs_ewma"], ForecastConfig())
    assert result.summary.loc[0, "observations"] > 100
    with pytest.raises(ValueError, match="no exposure"):
        validate_book({"BRENT": 0.0}, market.prices.data, ["fhs_ewma"], ForecastConfig())


def Settings_offline(settings):
    from mtwin.config import Settings

    return Settings(**{**settings.__dict__, "offline": True})


def test_every_chart_returns_a_renderable_figure(tmp_path, returns, prices):
    network = default_network()
    plan = optimize_flows(network, PRICES)
    econ = route_economics(network, PRICES)
    risk = margin_at_risk(plan, network, PRICES, returns, n_sims=500)
    pnl = pnl_from_exposures({"BRENT": 50e6}, returns)
    validation = run_validation(pnl, ["fhs_ewma"], ForecastConfig())
    signals = compute_signals(synthetic_chokepoints(["Suez Canal"], end="2025-12-31"))
    figures = [
        charts.price_chart(prices),
        charts.flow_chart(plan.flows),
        charts.flow_chart(plan.flows.assign(flow_kbd=0.0)),  # empty state
        charts.margin_waterfall_chart(econ.iloc[0]),
        charts.scenario_chart(run_scenarios(network, PRICES)),
        charts.margin_distribution_chart(
            risk.simulated, risk.base_margin_usd, risk.var_usd, risk.confidence
        ),
        charts.margin_distribution_chart(np.zeros(10), 0.0, 0.0, 0.95),  # degenerate distribution
        charts.var_backtest_chart(validation.forecasts["fhs_ewma"], "FHS"),
        charts.chokepoint_chart(signals, "Suez Canal"),
    ]
    for i, fig in enumerate(figures):
        path = tmp_path / f"{i}.png"
        fig.savefig(path)
        assert path.stat().st_size > 2000
