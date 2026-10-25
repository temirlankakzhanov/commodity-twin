"""Build ``site/data/site.json``: every figure on the landing page, computed from the snapshots.

The prices and chokepoint datasets resolve through ``DataService`` in offline mode, so they come
from the committed snapshots in ``data/snapshots`` (the build refuses synthetic data). The raw
2020 WTI series (``scripts/snapshot_raw_wti.py``) is read for the crisis chart only. The test
count is parsed from a real pytest run, never typed by hand.

Usage::

    make site-data                                         # runs pytest first, then this script
    python scripts/build_site_data.py --pytest-log FILE    # FILE holds the pytest output
"""

from __future__ import annotations

import argparse
import json
import re
import tempfile
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

import pandas as pd

from mtwin.config import load_settings
from mtwin.data import DataService
from mtwin.data.service import CHOKEPOINTS, LoadResult
from mtwin.risk import MODEL_LABELS, ForecastConfig, run_validation
from mtwin.risk.returns import log_returns, pnl_from_exposures
from mtwin.signals.chokepoints import (
    BASELINE_GAP,
    BASELINE_WINDOW,
    PCT_THRESHOLD,
    SHORT_WINDOW,
    Z_THRESHOLD,
    compute_signals,
    latest_flags,
)
from mtwin.trading import Scenario, book_exposures, default_network, optimize_flows
from mtwin.trading.network import Network
from mtwin.trading.optimizer import FlowPlan

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "site" / "data" / "site.json"
RAW_WTI = ROOT / "data" / "snapshots" / "site-raw-DCOILWTICO-2020.csv"

HORMUZ = "Strait of Hormuz"
QUALITY_WINDOW_DAYS = 60
STATUS_WINDOW_DAYS = 7
STATUS_PLACES = (
    "Strait of Hormuz",
    "Bab el-Mandeb Strait",
    "Suez Canal",
    "Malacca Strait",
    "Panama Canal",
)
MONITOR_SERIES_DAYS = 400  # covers Hormuz's Oct 2025 flags and the Mar 2026 collapse
MIN_REFERENCE_DAYS = 330  # a reference year with fewer reported days gives no status
VALIDATION_CFG = ForecastConfig(alpha=0.99, window=500)  # the Risk tab defaults
HEDGE_RATIO = 0.0  # the Risk tab default: plan-implied inventory, unhedged

SOURCES = {
    "fred": "U.S. Energy Information Administration, retrieved from FRED, "
    "Federal Reserve Bank of St. Louis",
    "portwatch": "UN Global Platform; IMF PortWatch",
}

_SUMMARY_TOKEN = re.compile(r"(\d+) (passed|failed|skipped|errors?|xfailed|xpassed)")


def parse_pytest_summary(text: str) -> dict[str, int]:
    """Counts from the last pytest summary line, e.g. ``94 passed, 1 skipped in 11.57s``.

    Raises:
        ValueError: if no summary line is found, or if any test failed or errored.
    """
    for line in reversed(text.strip().splitlines()):
        tokens = _SUMMARY_TOKEN.findall(line)
        if tokens and " in " in line:
            counts: dict[str, int] = {}
            for number, kind in tokens:
                key = "error" if kind.startswith("error") else kind
                counts[key] = counts.get(key, 0) + int(number)
            if counts.get("failed", 0) or counts.get("error", 0):
                raise ValueError(f"pytest did not pass: {line.strip()}")
            if not counts.get("passed"):
                raise ValueError(f"pytest summary reports no passed tests: {line.strip()}")
            return counts
    raise ValueError("No pytest summary line found")


def points(series: pd.Series, decimals: int = 2) -> list[list[Any]]:
    """``[[ISO date, value], ...]`` for a date-indexed series, missing values dropped."""
    clean = series.dropna()
    return [[ts.strftime("%Y-%m-%d"), round(float(v), decimals)] for ts, v in clean.items()]


def wti_2020(raw: pd.DataFrame, model_prices: pd.DataFrame) -> dict[str, Any]:
    """The raw 2020 WTI path, its minimum, and whether the model keeps that print."""
    series = raw.assign(date=pd.to_datetime(raw["date"])).set_index("date")["WTI"].sort_index()
    low_date = series.idxmin()
    in_model = low_date in model_prices.index and float(model_prices.at[low_date, "WTI"]) == float(
        series[low_date]
    )
    return {
        "series": points(series),
        "low": {"date": low_date.strftime("%Y-%m-%d"), "value": round(float(series.min()), 2)},
        "low_in_model": bool(in_model),
        "source": f"{SOURCES['fred']} (series DCOILWTICO, raw)",
        "note": "Negative print shown as reported. The model excludes non-positive prices "
        "(log returns are undefined), as documented in the methodology.",
    }


def brent_2022(prices: pd.DataFrame) -> dict[str, Any]:
    """Daily Brent in 2022 and its peak."""
    series = prices.loc["2022", "BRENT"]
    peak = series.idxmax()
    return {
        "series": points(series),
        "peak": {"date": peak.strftime("%Y-%m-%d"), "value": round(float(series.max()), 2)},
        "source": f"{SOURCES['fred']} (series DCOILBRENTEU)",
    }


def weekly_mean(transits: pd.DataFrame, name: str, start: str, end: str) -> pd.Series:
    """Weekly (Monday to Sunday) mean of daily transit calls for one chokepoint."""
    one = transits[transits["portname"] == name].set_index("date")["n_total"].sort_index()
    return one.loc[start:end].resample("W-SUN").mean()


def red_sea_2024(transits: pd.DataFrame) -> dict[str, Any]:
    """Weekly transit calls at Bab el-Mandeb and Suez, mid-2023 to end-2024."""
    start, end = "2023-07-03", "2024-12-29"
    return {
        "series": {
            name: points(weekly_mean(transits, name, start, end), 1)
            for name in ("Bab el-Mandeb Strait", "Suez Canal")
        },
        "unit": "weekly average of daily transit calls, all vessel types",
        "source": SOURCES["portwatch"],
    }


def coverage(transits: pd.DataFrame, days: int = QUALITY_WINDOW_DAYS) -> list[dict[str, Any]]:
    """Per chokepoint, how complete the last ``days`` calendar days are.

    Days absent from the data count as missing; reported zeros are counted separately.
    """
    end = transits["date"].max()
    calendar = pd.date_range(end - pd.Timedelta(days=days - 1), end, freq="D")
    rows = []
    for name, group in transits.groupby("portname", sort=True):
        series = group.set_index("date")["n_total"].reindex(calendar)
        rows.append(
            {
                "chokepoint": name,
                "days": days,
                "missing_days": int(series.isna().sum()),
                "zero_days": int((series == 0).sum()),
                "mean_calls": round(float(series.mean()), 1),
            }
        )
    return rows


def hormuz_traffic(transits: pd.DataFrame) -> dict[str, Any]:
    """PortWatch-reported Hormuz transit calls: monthly means and a data-quality check."""
    hormuz = transits[transits["portname"] == HORMUZ].set_index("date")["n_total"].sort_index()
    end = hormuz.index.max()
    recent = hormuz[hormuz.index > end - pd.Timedelta(days=QUALITY_WINDOW_DAYS)]
    year_2025 = hormuz.loc["2025"]
    monthly = hormuz.loc["2025":].resample("ME").mean()
    return {
        "label": "PortWatch-reported transit calls",
        "monthly": [[ts.strftime("%Y-%m"), round(float(v), 1)] for ts, v in monthly.items()],
        "mean_2025": round(float(year_2025.mean()), 1),
        "period_2025": [
            year_2025.index.min().strftime("%Y-%m-%d"),
            year_2025.index.max().strftime("%Y-%m-%d"),
        ],
        "mean_last_60d": round(float(recent.mean()), 1),
        "window": [recent.index.min().strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")],
        "coverage_last_60d": coverage(transits),
        "source": SOURCES["portwatch"],
    }


def chokepoint_status(
    transits: pd.DataFrame,
    places: tuple[str, ...] = STATUS_PLACES,
    days: int = STATUS_WINDOW_DAYS,
    reference_year: str = "2025",
) -> dict[str, Any]:
    """Mean daily transit calls over the last ``days`` calendar days versus a reference year.

    A place gets ``status: None`` (name only on the page) when the recent window has a missing
    day or the reference year has fewer than ``MIN_REFERENCE_DAYS`` reported days.
    """
    end = transits["date"].max()
    calendar = pd.date_range(end - pd.Timedelta(days=days - 1), end, freq="D")
    rows = []
    for name in places:
        series = transits[transits["portname"] == name].set_index("date")["n_total"].sort_index()
        recent = series.reindex(calendar)
        reference = series.loc[reference_year] if len(series) else series
        supported = recent.notna().all() and len(reference) >= MIN_REFERENCE_DAYS
        status = None
        if supported:
            recent_mean, ref_mean = float(recent.mean()), float(reference.mean())
            status = {
                "recent_mean": round(recent_mean, 1),
                "reference_mean": round(ref_mean, 1),
                "change_pct": round(100.0 * (recent_mean / ref_mean - 1.0)),
            }
        rows.append({"chokepoint": name, "status": status})
    return {
        "window": [calendar[0].strftime("%Y-%m-%d"), calendar[-1].strftime("%Y-%m-%d")],
        "reference_year": reference_year,
        "unit": "mean daily transit calls, all vessel types",
        "places": rows,
        "source": SOURCES["portwatch"],
    }


def plan_rows(plan: FlowPlan) -> list[dict[str, Any]]:
    """Terminal-panel rows: route, chokepoints, flow, unit margin, daily margin, status."""
    rows = []
    for row in plan.flows.itertuples(index=False):
        rows.append(
            {
                "route": row.route,
                "chokepoints": row.chokepoints,
                "flow_kbd": round(float(row.flow_kbd), 1),
                "margin_usd_bbl": round(float(row.margin_usd_bbl), 2),
                "daily_margin_usd": round(float(row.daily_margin_usd)),
                "status": "ACTIVE" if row.flow_kbd > 0 else "IDLE",
            }
        )
    return rows


def chokepoint_flows(plan: FlowPlan, network: Network) -> dict[str, float]:
    """kb/d the plan sends through each chokepoint."""
    totals = dict.fromkeys(network.chokepoint_capacity_kbd, 0.0)
    for route in network.routes:
        flow = float(plan.flows.loc[plan.flows["route"] == route.name, "flow_kbd"].sum())
        for name in route.chokepoints:
            totals[name] += flow
    return {name: round(value, 1) for name, value in totals.items()}


def port_labels(plan: FlowPlan, network: Network) -> dict[str, dict[str, Any]]:
    """Map labels for the ports: role and the volume the plan moves through them."""
    flows = plan.flows
    labels: dict[str, dict[str, Any]] = {}
    for origin in network.origins:
        shipped = float(flows.loc[flows["origin"] == origin.name, "flow_kbd"].sum())
        labels[origin.name] = {"role": "origin", "flow_kbd": round(shipped, 1)}
    for dest in network.destinations:
        received = float(flows.loc[flows["destination"] == dest.name, "flow_kbd"].sum())
        labels[dest.name] = {"role": "destination", "flow_kbd": round(received, 1)}
    return labels


def hormuz_closure(network: Network, prices: Mapping[str, float]) -> dict[str, Any]:
    """Base plan versus a full Hormuz closure (no other shock) on the illustrative network."""
    base = optimize_flows(network, prices)
    closed = optimize_flows(network, prices, Scenario("Hormuz closed", closed=(HORMUZ,)))
    base_volume = float(base.flows["flow_kbd"].sum())
    closed_volume = float(closed.flows["flow_kbd"].sum())
    delta = closed.total_daily_margin_usd - base.total_daily_margin_usd
    return {
        "label": "illustrative network, not a forecast",
        "base": {
            "status": base.status,
            "daily_margin_usd": round(base.total_daily_margin_usd),
            "volume_kbd": round(base_volume, 1),
            "routes": plan_rows(base),
            "chokepoint_flows_kbd": chokepoint_flows(base, network),
            "ports": port_labels(base, network),
        },
        "closed": {
            "status": closed.status,
            "daily_margin_usd": round(closed.total_daily_margin_usd),
            "volume_kbd": round(closed_volume, 1),
            "routes": plan_rows(closed),
            "chokepoint_flows_kbd": chokepoint_flows(closed, network),
            "ports": port_labels(closed, network),
        },
        "delta_daily_margin_usd": round(delta),
        "stranded_kbd": round(base_volume - closed_volume, 1),
    }


def scenario_id(chokepoint: str) -> str:
    """Stable slug for a chokepoint scenario, e.g. ``strait-of-hormuz``."""
    return re.sub(r"[^a-z0-9]+", "-", chokepoint.lower()).strip("-")


def scenarios(network: Network, prices: Mapping[str, float]) -> dict[str, Any]:
    """Base plan and one full closure per chokepoint that any route passes through.

    Every closure is solved with the same ``optimize_flows`` / ``Scenario`` call as the Hormuz
    closure. ``same_as_base`` marks closures that leave every route flow unchanged; the routes
    the closure removes are listed either way, so the shrinking set of fallback lanes is visible.
    """
    used = {name for route in network.routes for name in route.chokepoints}
    names = [name for name in network.chokepoint_capacity_kbd if name in used]
    base = optimize_flows(network, prices)
    base_flow = dict(zip(base.flows["route"], base.flows["flow_kbd"], strict=True))
    base_volume = float(base.flows["flow_kbd"].sum())

    def entry(plan: FlowPlan, closed: str | None) -> dict[str, Any]:
        volume = float(plan.flows["flow_kbd"].sum())
        flow = dict(zip(plan.flows["route"], plan.flows["flow_kbd"], strict=True))
        removed = [r.name for r in network.routes if closed and closed in r.chokepoints]
        return {
            "name": closed or "Base case",
            "closed": [closed] if closed else [],
            "status": plan.status,
            "feasible": plan.status == "optimal",
            "same_as_base": all(abs(flow[k] - base_flow[k]) < 1e-6 for k in base_flow),
            "daily_margin_usd": round(plan.total_daily_margin_usd),
            "delta_daily_margin_usd": round(
                plan.total_daily_margin_usd - base.total_daily_margin_usd
            ),
            "volume_kbd": round(volume, 1),
            "stranded_kbd": round(base_volume - volume, 1),
            "routes": [
                {k: row[k] for k in ("route", "flow_kbd", "daily_margin_usd", "status")}
                for row in plan_rows(plan)
            ],
            "removed_routes": removed,
            "removed_idle_routes": [name for name in removed if base_flow[name] <= 0.0],
        }

    items = {"base": entry(base, None)}
    for name in names:
        closed = optimize_flows(network, prices, Scenario(f"{name} closed", closed=(name,)))
        items[scenario_id(name)] = entry(closed, name)
    return {
        "label": "illustrative network, not a forecast",
        "order": list(items),
        "items": items,
    }


def validation(prices: pd.DataFrame, network: Network, plan: FlowPlan) -> dict[str, Any]:
    """Verdicts of all VaR/ES models on the Risk tab's default book and settings."""
    latest = {name: float(prices[name].iloc[-1]) for name in network.benchmarks}
    exposures = book_exposures(plan, network, latest, HEDGE_RATIO)
    pnl = pnl_from_exposures(exposures, log_returns(prices))
    result = run_validation(pnl, list(MODEL_LABELS), VALIDATION_CFG)
    keep = ["model", "observations", "exceptions", "expected", "kupiec_p", "cond_coverage_p"]
    keep += ["exc_last_250", "basel_zone", "es_z2", "verdict"]
    table = result.summary[keep]
    return {
        "settings": {
            "book": "plan-implied inventory in transit, unhedged",
            "exposures_usd": {k: round(v) for k, v in exposures.items()},
            "confidence": VALIDATION_CFG.alpha,
            "window_days": VALIDATION_CFG.window,
            "first_forecast": result.forecasts[next(iter(MODEL_LABELS))]
            .index[0]
            .strftime("%Y-%m-%d"),
        },
        "models": json.loads(table.to_json(orient="records")),
        "note": "Verdicts depend on the book, confidence level, window and data date; "
        "other settings give other verdicts.",
    }


def monitor_flags(transits: pd.DataFrame) -> list[dict[str, Any]]:
    """The traffic monitor's latest reading per chokepoint (for the limits section)."""
    flags = latest_flags(compute_signals(transits[transits["portname"].isin(CHOKEPOINTS)]))
    flags = flags.assign(date=flags["date"].dt.strftime("%Y-%m-%d"))
    return json.loads(flags.round(3).to_json(orient="records"))


def _runs(mask: pd.Series) -> list[list[int]]:
    """Index ranges [first, last] of consecutive True values."""
    runs: list[list[int]] = []
    start = None
    values = mask.to_numpy()
    for i, on in enumerate(values):
        if on and start is None:
            start = i
        if not on and start is not None:
            runs.append([start, i - 1])
            start = None
    if start is not None:
        runs.append([start, len(values) - 1])
    return runs


def _num(value: float, digits: int = 1) -> float | None:
    return None if pd.isna(value) else round(float(value), digits)


def monitor_series(transits: pd.DataFrame, days: int = MONITOR_SERIES_DAYS) -> dict[str, Any]:
    """Daily monitor history per chokepoint, plus why the last reading is or is not flagged.

    ``ma7`` and ``baseline`` come straight from ``compute_signals``; ``flagged`` is given as index
    ranges into the shared date axis. For the last reading, ``spread`` is the baseline window's
    standard deviation implied by the z-score and ``window_min`` / ``window_max`` bound the lagged
    7-day averages that the baseline is built from.
    """
    signals = compute_signals(transits[transits["portname"].isin(CHOKEPOINTS)])
    end = signals["date"].max()
    start = end - pd.Timedelta(days=days - 1)
    axis = pd.date_range(start, end, freq="D")
    series: dict[str, Any] = {}
    for name, group in signals.groupby("chokepoint"):
        frame = group.set_index("date").reindex(axis)
        full = group.set_index("date")["ma7"]
        lagged = full.shift(BASELINE_GAP).iloc[-BASELINE_WINDOW:]
        last = frame.iloc[-1]
        z = last["zscore"]
        series[str(name)] = {
            "ma7": [_num(v) for v in frame["ma7"]],
            "baseline": [_num(v) for v in frame["baseline"]],
            "flagged": _runs(frame["flagged"].fillna(False).astype(bool)),
            "latest": {
                "ma7": _num(last["ma7"]),
                "baseline": _num(last["baseline"]),
                "pct_change": _num(last["pct_change"], 3),
                "zscore": _num(z, 2),
                "flagged": bool(last["flagged"]),
                "pct_condition": bool(last["pct_change"] < PCT_THRESHOLD),
                "z_condition": bool(z < Z_THRESHOLD),
                "spread": _num((last["ma7"] - last["baseline"]) / z) if z else None,
                "window_min": _num(lagged.min()),
                "window_max": _num(lagged.max()),
            },
        }
    return {
        "start": start.strftime("%Y-%m-%d"),
        "days": days,
        "pct_threshold": PCT_THRESHOLD,
        "z_threshold": Z_THRESHOLD,
        "short_window_days": SHORT_WINDOW,
        "label": "PortWatch-reported transit calls, 7-day average vs the monitor baseline",
        "source": SOURCES["portwatch"],
        "series": series,
    }


def build(
    prices: LoadResult,
    transits: LoadResult,
    raw_wti: pd.DataFrame,
    tests: Mapping[str, int],
) -> dict[str, Any]:
    """Assemble the landing-page payload from already loaded inputs (no I/O)."""
    for result in (prices, transits):
        if result.source != "snapshot":
            raise ValueError(f"{result.key} resolved to '{result.source}', expected a snapshot")
    network = default_network()
    latest = {name: float(prices.data[name].iloc[-1]) for name in network.benchmarks}
    closure = hormuz_closure(network, latest)
    base_plan = optimize_flows(network, latest)
    return {
        "as_of": {
            "prices": prices.data.index.max().strftime("%Y-%m-%d"),
            "transits": transits.data["date"].max().strftime("%Y-%m-%d"),
            "snapshot_fetched": prices.fetched_at.strftime("%Y-%m-%d")
            if prices.fetched_at
            else None,
        },
        "prices_latest": {k: round(v, 2) for k, v in latest.items()},
        "network": {
            "label": "illustrative network: supplies, demands, freight and capacities are "
            "assumptions, not market data",
            "origins": [o.name for o in network.origins],
            "destinations": [d.name for d in network.destinations],
            "routes": [
                {"name": r.name, "origin": r.origin, "destination": r.destination}
                | {"chokepoints": list(r.chokepoints)}
                for r in network.routes
            ],
        },
        "hormuz_closure": closure,
        "scenarios": scenarios(network, latest),
        "validation": validation(prices.data, network, base_plan),
        "crises": {
            "wti_2020": wti_2020(raw_wti, prices.data),
            "brent_2022": brent_2022(prices.data),
            "red_sea_2024": red_sea_2024(transits.data),
        },
        "hormuz_traffic": hormuz_traffic(transits.data),
        "monitor": monitor_flags(transits.data),
        "monitor_series": monitor_series(transits.data),
        "monitor_method": {
            "baseline_window_days": BASELINE_WINDOW,
            "baseline_gap_days": BASELINE_GAP,
        },
        "chokepoint_status": chokepoint_status(transits.data),
        "facts": {
            "risk_models": len(MODEL_LABELS),
            "tests_passed": int(tests["passed"]),
            "tests_skipped": int(tests.get("skipped", 0)),
            "routes": len(network.routes),
            "chokepoints_monitored": len(CHOKEPOINTS),
        },
        "sources": SOURCES,
    }


def main(argv: list[str] | None = None) -> None:
    """CLI entry point: load snapshots offline, build the payload, write the JSON."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pytest-log", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)

    tests = parse_pytest_summary(args.pytest_log.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as tmp:
        settings = replace(load_settings(), offline=True, cache_dir=Path(tmp))
        service = DataService(settings)
        payload = build(service.prices(), service.chokepoints(), pd.read_csv(RAW_WTI), tests)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {args.out.relative_to(ROOT)} (tests passed: {tests['passed']})")


if __name__ == "__main__":
    main()
