"""Render the figures used in the README from synthetic data (reproducible, no network).

Usage: ``python scripts/make_readme_figures.py`` writes PNG files to ``docs/img``.
"""

from __future__ import annotations

from pathlib import Path

from mtwin.data.synthetic import synthetic_chokepoints, synthetic_prices
from mtwin.risk import MODEL_LABELS, ForecastConfig, run_validation
from mtwin.risk.returns import log_returns, pnl_from_exposures
from mtwin.risk.validation import render_report
from mtwin.signals.chokepoints import compute_signals
from mtwin.trading import default_network, margin_at_risk, optimize_flows, run_scenarios
from mtwin.ui import charts

END = "2026-01-30"  # fixed so the figures are reproducible
OUT = Path(__file__).resolve().parents[1] / "docs" / "img"


def main() -> None:
    """Generate all README figures."""
    OUT.mkdir(parents=True, exist_ok=True)
    prices = synthetic_prices("2010-01-01", end=END)
    returns = log_returns(prices)
    last = {"BRENT": float(prices["BRENT"].iloc[-1]), "WTI": float(prices["WTI"].iloc[-1])}
    network = default_network()
    plan = optimize_flows(network, last)

    figures = {
        "flows.png": charts.flow_chart(plan.flows),
        "scenarios.png": charts.scenario_chart(run_scenarios(network, last)),
    }
    risk = margin_at_risk(plan, network, last, returns)
    figures["margin_at_risk.png"] = charts.margin_distribution_chart(
        risk.simulated, risk.base_margin_usd, risk.var_usd, risk.confidence
    )

    pnl = pnl_from_exposures({"BRENT": 50e6}, returns)
    result = run_validation(pnl, ["fhs_ewma"], ForecastConfig())
    figures["backtest.png"] = charts.var_backtest_chart(
        result.forecasts["fhs_ewma"], "Filtered HS (EWMA), unhedged Brent book"
    )

    signals = compute_signals(synthetic_chokepoints(["Suez Canal"], end=END))
    figures["chokepoint.png"] = charts.chokepoint_chart(signals, "Suez Canal")

    # A sample memo on the same synthetic book, all five models, linked from the README.
    full = run_validation(pnl, list(MODEL_LABELS), ForecastConfig())
    first, last_day = full.forecasts["historical"].index[[0, -1]]
    memo = render_report(
        full,
        title="Sample validation memo (synthetic data, unhedged Brent book of USD 50M)",
        data_label="SYNTHETIC demo data, not market data",
        period=f"{str(first)[:10]} to {str(last_day)[:10]}",
    )
    (OUT.parent / "sample_validation_memo.md").write_text(memo + "\n", encoding="utf-8")
    print("wrote", OUT.parent / "sample_validation_memo.md")

    for name, fig in figures.items():
        fig.savefig(OUT / name)
        print("wrote", OUT / name)


if __name__ == "__main__":
    main()
