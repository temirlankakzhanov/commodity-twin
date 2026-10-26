"""Streamlit pages. Thin by design: widgets and layout only, logic lives in the layers below."""

from __future__ import annotations

import logging
from datetime import datetime

import pandas as pd
import streamlit as st

from mtwin import __version__
from mtwin.config import load_settings
from mtwin.data import DataService
from mtwin.data.catalog import DUCKDB_AVAILABLE, describe_cache
from mtwin.data.providers.portwatch import CITATION as PORTWATCH_CITATION
from mtwin.risk import MODEL_LABELS, ForecastConfig
from mtwin.risk.returns import log_returns
from mtwin.risk.validation import render_report
from mtwin.trading import (
    BASE,
    PRESET_SCENARIOS,
    Scenario,
    book_exposures,
    default_network,
    margin_at_risk,
    optimize_flows,
    route_economics,
    run_scenarios,
)
from mtwin.trading.scenarios import scenario_from_signals
from mtwin.ui import charts
from mtwin.ui.compute import MarketData, as_of, latest_prices, load_market, monitor, validate_book

logger = logging.getLogger(__name__)
DISCLAIMER = (
    "Portfolio project for education and research. Network parameters are illustrative "
    "assumptions. Nothing here is investment advice."
)


@st.cache_resource(show_spinner=False)
def get_service() -> DataService:
    """One DataService per server process (it holds provider cooldown state)."""
    return DataService()


@st.cache_resource(ttl=3600, show_spinner="Loading market data...")
def cached_market(demo: bool, refresh_token: int) -> MarketData:
    """Market data, cached for an hour per (mode, refresh) combination.

    ``cache_resource`` rather than ``cache_data``: the value is never pickled. After a source
    change Streamlit re-imports ``mtwin`` while ``get_service`` keeps the old ``DataService``,
    whose results are instances of the old classes; pickling them fails. The shared
    ``MarketData`` is frozen and the UI never modifies its frames in place.
    """
    return load_market(get_service(), demo=demo, refresh=refresh_token > 0)


def usd_m(value: float) -> str:
    """Format USD as a signed number of millions, e.g. ``-$1.16M``."""
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value) / 1e6:,.2f}M"


def show_fig(fig) -> None:
    """Render a matplotlib figure."""
    st.pyplot(fig)


def data_banner(market: MarketData) -> None:
    """State plainly where the data comes from."""
    if market.any_synthetic:
        st.warning(
            "SYNTHETIC DEMO DATA in use for: "
            + ", ".join(
                name
                for name, res in (
                    ("prices", market.prices),
                    ("chokepoint traffic", market.chokepoints),
                    ("macro", market.macro),
                )
                if not res.is_real
            )
            + ". Figures illustrate the methods only and are not market data."
        )
    else:
        st.success(
            "Real data: "
            + "; ".join(
                sorted({r.label for r in (market.prices, market.chokepoints, market.macro)})
            )
        )
    notes = [n for r in (market.prices, market.chokepoints, market.macro) for n in r.notes]
    if notes:
        with st.expander("Data notes"):
            for note in dict.fromkeys(notes):
                st.write("- " + note)


def sidebar() -> tuple[bool, int]:
    """Global controls. Returns ``(demo_mode, refresh_token)``."""
    st.sidebar.header("Data")
    mode = st.sidebar.radio(
        "Mode",
        ["Live data (with fallbacks)", "Synthetic demo"],
        help="Live mode falls back to cache, snapshot and finally synthetic data.",
    )
    token = int(st.session_state.get("refresh_token", 0))
    if st.sidebar.button("Refresh from sources"):
        token += 1
        st.session_state["refresh_token"] = token
    st.sidebar.caption(DISCLAIMER)
    st.sidebar.caption(f"commodity-twin v{__version__}")
    return mode == "Synthetic demo", token


def market_inputs(prices: pd.DataFrame) -> dict[str, float]:
    """Benchmark price inputs, pre-filled with the latest data."""
    last = latest_prices(prices)
    key = as_of(prices)
    st.sidebar.header("Market inputs")
    st.sidebar.caption(f"Latest prices as of {key}. Override to test a view.")
    return {
        name: float(
            st.sidebar.number_input(
                f"{name} (USD/bbl)",
                min_value=1.0,
                max_value=500.0,
                value=round(value, 2),
                step=0.5,
                key=f"{name}-{key}",
            )
        )
        for name, value in last.items()
    }


def overview_tab(market: MarketData, prices: dict[str, float], returns: pd.DataFrame) -> None:
    """Headline numbers and the base-case plan."""
    network = default_network()
    plan = optimize_flows(network, prices)
    risk = None
    if plan.status == "optimal" and plan.flows["flow_kbd"].sum() > 0:
        risk = margin_at_risk(plan, network, prices, returns)
    scen = run_scenarios(network, prices)
    worst = scen.iloc[scen["delta_vs_base_usd"].idxmin()]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Base daily margin", usd_m(plan.total_daily_margin_usd))
    c2.metric("Volume", f"{plan.flows['flow_kbd'].sum():,.0f} kb/d")
    c3.metric("95% margin-at-risk (20d)", usd_m(risk.var_usd) if risk else "n/a")
    c4.metric(
        "Worst preset scenario", usd_m(worst["delta_vs_base_usd"]), help=str(worst["scenario"])
    )
    show_fig(charts.price_chart(market.prices.data))
    st.subheader("Base-case plan")
    used = plan.flows[plan.flows["flow_kbd"] > 0][
        ["route", "flow_kbd", "margin_usd_bbl", "daily_margin_usd"]
    ]
    st.dataframe(used.round(2), hide_index=True)


def optimizer_tab(prices: dict[str, float]) -> None:
    """Route economics, optimal flows and shadow prices."""
    network = default_network()
    econ = route_economics(network, prices)
    plan = optimize_flows(network, prices)
    st.write(
        "Linear programme: maximise margin subject to origin supply, destination demand and "
        "chokepoint capacity. Shadow prices show the value of one more kb/d of each limit."
    )
    if plan.status != "optimal":
        st.error(f"Optimiser did not converge: {plan.status}")
        return
    show_fig(charts.flow_chart(plan.flows))
    route = st.selectbox("Route unit economics", econ["route"].tolist())
    show_fig(charts.margin_waterfall_chart(econ[econ["route"] == route].iloc[0]))
    st.subheader("Shadow prices of binding constraints")
    binding = plan.shadow_prices[
        plan.shadow_prices["binding"] & (plan.shadow_prices["shadow_usd_bbl"] > 0)
    ]
    st.dataframe(binding.drop(columns="binding").round(3), hide_index=True)
    with st.expander("All routes"):
        st.dataframe(econ.round(3), hide_index=True)


def scenario_tab(prices: dict[str, float], flags: pd.DataFrame) -> None:
    """Preset, custom and monitor-implied stress scenarios."""
    network = default_network()
    options = {s.name: s for s in PRESET_SCENARIOS}
    monitor_scenario = scenario_from_signals(flags) if not flags.empty else None
    if monitor_scenario is not None:
        options[monitor_scenario.name] = monitor_scenario
    options["Custom"] = Scenario("Custom")
    choice = st.selectbox("Scenario", list(options))
    scenario = options[choice]
    if choice == "Custom":
        closed = st.multiselect("Closed chokepoints", sorted(network.chokepoint_capacity_kbd))
        freight = st.slider("Freight multiplier", 0.5, 3.0, 1.0, 0.05)
        shock = st.slider("Price shock (Brent and WTI, %)", -50, 100, 0, 5)
        premium = st.slider(
            "War-risk premium on all closed or restricted chokepoints (USD/bbl)",
            0.0,
            2.0,
            0.0,
            0.05,
        )
        scenario = Scenario(
            "Custom",
            closed=tuple(closed),
            freight_multiplier=freight,
            insurance_add=dict.fromkeys(closed, premium),
            price_shock={"BRENT": shock / 100, "WTI": shock / 100},
        )
    elif scenario.description:
        st.caption(scenario.description)

    table = run_scenarios(network, prices, [BASE, scenario] if scenario is not BASE else [BASE])
    plan = optimize_flows(network, prices, scenario)
    base = table.iloc[0]["daily_margin_usd"]
    c1, c2 = st.columns(2)
    c1.metric(
        "Scenario daily margin",
        usd_m(plan.total_daily_margin_usd),
        f"{usd_m(plan.total_daily_margin_usd - base)} vs base",
    )
    c2.metric("Volume", f"{plan.flows['flow_kbd'].sum():,.0f} kb/d")
    show_fig(charts.flow_chart(plan.flows))
    st.subheader("All preset scenarios")
    all_scen = run_scenarios(network, prices)
    show_fig(charts.scenario_chart(all_scen))
    st.dataframe(all_scen.round(0), hide_index=True)


def risk_tab(prices_df: pd.DataFrame, prices: dict[str, float]) -> None:
    """Independent model validation lab."""
    network = default_network()
    plan = optimize_flows(network, prices)
    st.write(
        "Backtest several VaR/ES models on the same book, the way a validation team would: "
        "Kupiec, Christoffersen, Basel traffic light and Acerbi-Szekely ES."
    )
    source = st.radio(
        "Book", ["Plan-implied inventory", "Custom exposures (USD million)"], horizontal=True
    )
    if source.startswith("Plan"):
        hedge = st.slider("Hedge ratio (short destination benchmark)", 0, 100, 0, 10) / 100
        exposures = book_exposures(plan, network, prices, hedge)
        st.caption(
            "Cargoes in transit, long the origin benchmark, hedged "
            f"{hedge:.0%} against the destination benchmark: "
            + (", ".join(f"{k} {v / 1e6:,.0f}M" for k, v in exposures.items()) or "no net exposure")
        )
    else:
        cols = st.columns(3)
        exposures = {
            name: cols[i].number_input(
                f"{name} (USD M)", value=50.0 if name == "BRENT" else 0.0, step=10.0
            )
            * 1e6
            for i, name in enumerate(("BRENT", "WTI", "HENRY_HUB"))
        }
    c1, c2, c3 = st.columns(3)
    alpha = c1.selectbox("Confidence", [0.99, 0.975, 0.95], format_func=lambda a: f"{a:.1%}")
    window = c2.slider("Estimation window (days)", 250, 1000, 500, 50)
    models = c3.multiselect(
        "Models", list(MODEL_LABELS), default=list(MODEL_LABELS), format_func=MODEL_LABELS.get
    )
    if not models:
        st.info("Select at least one model.")
        return
    try:
        result = validate_book(
            exposures, prices_df, models, ForecastConfig(alpha=alpha, window=window)
        )
    except (ValueError, KeyError) as exc:
        st.error(str(exc))
        return
    summary = result.summary
    st.dataframe(summary.drop(columns=["avg_var_usd", "avg_es_usd"]), hide_index=True)
    pick = st.selectbox("Backtest chart", models, format_func=MODEL_LABELS.get)
    show_fig(charts.var_backtest_chart(result.forecasts[pick], MODEL_LABELS[pick]))
    first, last = result.forecasts[pick].index[[0, -1]]
    report = render_report(
        result,
        title="Independent model validation memo",
        data_label=f"{prices_df.attrs.get('label', 'price history')}",
        period=f"{str(first)[:10]} to {str(last)[:10]}",
    )
    st.download_button(
        "Download validation memo (Markdown)",
        report,
        file_name="validation_memo.md",
        mime="text/markdown",
    )


def chokepoint_tab(market: MarketData, signals: pd.DataFrame, flags: pd.DataFrame) -> None:
    """Chokepoint traffic monitor."""
    st.write("Early-warning signal from daily transit calls. " + PORTWATCH_CITATION)
    if signals.empty:
        st.info("No chokepoint data available.")
        return
    show = flags[["chokepoint", "ma7", "baseline", "pct_change", "zscore", "flagged"]].copy()
    show["pct_change"] = (show["pct_change"] * 100).round(1)
    st.dataframe(show.round(2), hide_index=True)
    name = st.selectbox("Chokepoint", sorted(signals["chokepoint"].unique()))
    show_fig(charts.chokepoint_chart(signals, name))


def data_tab(market: MarketData) -> None:
    """Provenance, methodology and limitations."""
    st.subheader("Data provenance")
    rows = []
    for label, res in (
        ("Prices", market.prices),
        ("Chokepoint traffic", market.chokepoints),
        ("Macro", market.macro),
    ):
        fetched = (
            res.fetched_at.strftime("%Y-%m-%d %H:%M UTC")
            if isinstance(res.fetched_at, datetime)
            else "-"
        )
        rows.append(
            {
                "dataset": label,
                "status": res.source,
                "source": res.label,
                "fetched": fetched,
                "rows": len(res.data),
            }
        )
    st.dataframe(pd.DataFrame(rows), hide_index=True)
    duckdb_state = "available" if DUCKDB_AVAILABLE else "not installed (pandas fallback)"
    st.markdown(
        "- **Prices**: FRED daily spot series (Brent, WTI, Henry Hub). Non-positive prints "
        "(for example WTI on 20 Apr 2020) are treated as missing.\n"
        "- **Chokepoints**: IMF PortWatch daily transit calls. " + PORTWATCH_CITATION + "\n"
        "- **Macro**: World Bank indicators.\n"
        "- **Fallback chain**: fresh cache, live API, stale cache, committed snapshot, "
        "synthetic data.\n"
        f"- **Cache catalogue** uses DuckDB: {duckdb_state}."
    )
    try:
        catalogue = describe_cache(load_settings().cache_dir)
        if not catalogue.empty:
            st.dataframe(catalogue, hide_index=True)
    except Exception:
        logger.exception("Cache catalogue failed")
    st.subheader("Method notes and limitations")
    st.markdown(
        "- VaR/ES are one-day, positive-loss numbers; exceptions are `loss > VaR`.\n"
        "- GARCH parameters are estimated once on the first 750 days and frozen.\n"
        "- Backtests at 99% have limited power; the Basel zone uses the last 250 days.\n"
        "- The trade network is illustrative; the optimiser is a single-period LP.\n"
        "- Flows between same-benchmark ports carry no flat-price risk; margin-at-risk adds an "
        "assumed basis volatility.\n"
        f"- {DISCLAIMER}"
    )


def run() -> None:
    """Application entry point."""
    st.set_page_config(page_title="Commodity Merchant Digital Twin", page_icon=None, layout="wide")
    st.title("Commodity Merchant Digital Twin")
    st.caption("Physical crude flows, chokepoint stress and independent VaR/ES model validation")
    demo, token = sidebar()
    market = cached_market(demo, token)
    data_banner(market)
    # A shallow copy: the cached frame is shared between sessions and is never modified.
    prices_df = market.prices.data.copy(deep=False)
    prices_df.attrs["label"] = market.prices.label
    prices = market_inputs(prices_df)
    returns = log_returns(prices_df)
    signals, flags = monitor(market.chokepoints.data)

    tabs = st.tabs(
        [
            "Overview",
            "Flow optimizer",
            "Stress scenarios",
            "Risk & validation",
            "Chokepoint monitor",
            "Data & methodology",
        ]
    )
    with tabs[0]:
        overview_tab(market, prices, returns)
    with tabs[1]:
        optimizer_tab(prices)
    with tabs[2]:
        scenario_tab(prices, flags)
    with tabs[3]:
        risk_tab(prices_df, prices)
    with tabs[4]:
        chokepoint_tab(market, signals, flags)
    with tabs[5]:
        data_tab(market)
