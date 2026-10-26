"""Landing-page data builder (scripts/build_site_data.py) and the raw WTI snapshot."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from mtwin.config import load_settings
from mtwin.data import DataService
from mtwin.data.service import LoadResult
from mtwin.data.transforms import clean_prices
from mtwin.risk.returns import log_returns, pnl_from_exposures
from mtwin.trading import book_exposures, default_network, optimize_flows
from mtwin.trading.network import Destination, Network, Origin, Route
from scripts import build_site_data as site
from scripts.snapshot_raw_wti import raw_frame


def test_parse_pytest_summary_reads_counts():
    log = "....s....\n94 passed, 1 skipped in 11.57s\n"
    assert site.parse_pytest_summary(log) == {"passed": 94, "skipped": 1}
    framed = "===== 12 passed, 2 skipped, 3 warnings in 0.50s =====\n"
    assert site.parse_pytest_summary(framed) == {"passed": 12, "skipped": 2}


@pytest.mark.parametrize(
    "log",
    [
        "2 failed, 90 passed in 3.1s",
        "90 passed, 1 error in 3.1s",
        "5 skipped in 0.1s",
        "no summary here",
        "",
    ],
)
def test_parse_pytest_summary_rejects_failures_and_garbage(log):
    with pytest.raises(ValueError):
        site.parse_pytest_summary(log)


def test_wti_2020_keeps_the_negative_print_and_reports_model_exclusion():
    raw = pd.DataFrame(
        {"date": ["2020-04-17", "2020-04-20", "2020-04-21"], "WTI": [18.31, -36.98, 8.91]}
    )
    model = clean_prices(raw.assign(date=pd.to_datetime(raw["date"])).set_index("date"), min_rows=1)
    out = site.wti_2020(raw, model)
    assert out["low"] == {"date": "2020-04-20", "value": -36.98}
    assert out["series"][1] == ["2020-04-20", -36.98]
    assert out["low_in_model"] is False
    # Cleaning carries the previous price (17 Apr, 18.31) forward into 20 Apr.
    assert out["model_value"] == 18.31 and "previous price" in out["note"]
    assert "DCOILWTICO" in out["source"] and "FRED" in out["source"]


def test_committed_raw_wti_snapshot_has_the_negative_print_that_the_model_drops():
    raw = pd.read_csv(site.RAW_WTI)
    row = raw.loc[raw["date"] == "2020-04-20", "WTI"]
    assert float(row.iloc[0]) == -36.98
    cleaned = clean_prices(raw.assign(date=pd.to_datetime(raw["date"])).set_index("date"))
    assert (cleaned["WTI"] > 0).all()


def test_committed_snapshot_keeps_20_april_2020_with_the_previous_wti_price(tmp_path):
    settings = replace(load_settings(), offline=True, cache_dir=tmp_path)
    prices = DataService(settings).prices()
    assert prices.source == "snapshot"
    data = prices.data
    day = pd.Timestamp("2020-04-20")
    # The negative print is replaced by the previous price, and the day stays in the sample.
    assert day in data.index and data.at[day, "WTI"] == 18.31
    # The crash therefore lands on 21 Apr: the largest loss of the plan-implied book.
    network = default_network()
    latest = {name: float(data[name].iloc[-1]) for name in network.benchmarks}
    plan = optimize_flows(network, latest)
    exposures = book_exposures(plan, network, latest, site.HEDGE_RATIO)
    pnl = pnl_from_exposures(exposures, log_returns(data))
    assert pnl.idxmin() == pd.Timestamp("2020-04-21")


def test_raw_frame_does_not_drop_negative_values():
    series = pd.Series(
        [18.31, -36.98], index=pd.DatetimeIndex(["2020-04-17", "2020-04-20"], name="date")
    )
    frame = raw_frame(series)
    assert frame.to_dict("records") == [
        {"date": "2020-04-17", "WTI": 18.31},
        {"date": "2020-04-20", "WTI": -36.98},
    ]


def _transits(name: str, values: list[float | None], start: str) -> pd.DataFrame:
    dates = pd.date_range(start, periods=len(values), freq="D")
    rows = [(d, name, v) for d, v in zip(dates, values, strict=True) if v is not None]
    return pd.DataFrame(rows, columns=["date", "portname", "n_total"])


def test_coverage_counts_missing_and_zero_days():
    frame = pd.concat(
        [
            _transits("A", [5, None, 0, 7], "2024-01-01"),  # one gap, one reported zero
            _transits("B", [1, 1, 1, 1], "2024-01-01"),
        ]
    )
    rows = {r["chokepoint"]: r for r in site.coverage(frame, days=4)}
    assert rows["A"]["missing_days"] == 1 and rows["A"]["zero_days"] == 1
    assert rows["A"]["mean_calls"] == 4.0  # (5 + 0 + 7) / 3
    assert rows["B"] == {
        "chokepoint": "B",
        "days": 4,
        "missing_days": 0,
        "zero_days": 0,
        "mean_calls": 1.0,
    }


def test_weekly_mean_uses_calendar_weeks_and_no_future_data():
    # Monday 2024-01-01 .. Sunday 2024-01-14: two full weeks with means 4 and 11.
    frame = _transits("A", list(range(1, 15)), "2024-01-01")
    weekly = site.weekly_mean(frame, "A", "2024-01-01", "2024-01-14")
    assert weekly.tolist() == [4.0, 11.0]
    changed = frame.copy()
    changed.loc[changed["date"] == "2024-01-14", "n_total"] = 1000.0
    assert site.weekly_mean(changed, "A", "2024-01-01", "2024-01-14").iloc[0] == 4.0


def test_hormuz_closure_strands_volume_and_empties_hormuz_routes():
    network = default_network()
    out = site.hormuz_closure(network, {"BRENT": 80.0, "WTI": 76.0})
    assert out["closed"]["chokepoint_flows_kbd"]["Strait of Hormuz"] == 0.0
    stranded = out["base"]["volume_kbd"] - out["closed"]["volume_kbd"]
    assert out["stranded_kbd"] == pytest.approx(stranded)
    delta = out["closed"]["daily_margin_usd"] - out["base"]["daily_margin_usd"]
    assert abs(out["delta_daily_margin_usd"] - delta) <= 1
    # Ras Tanura only ships through Hormuz, so it ships nothing once Hormuz is closed.
    assert out["closed"]["ports"]["Ras Tanura"] == {"role": "origin", "flow_kbd": 0.0}
    assert out["label"] == "illustrative network, not a forecast"


def _two_strait_network() -> Network:
    """One origin, one destination 2 USD/bbl richer, three lanes through straits C1 or C2.

    With insurance and financing set to zero, margin = 2 - freight: A (C1) 1.5, B (C2) 1.0,
    C (C1) 0.2 USD/bbl.
    """
    return Network(
        origins=(Origin("O", "X", 0.0, 100.0),),
        destinations=(Destination("D", "X", 2.0, 100.0),),
        routes=(
            Route("A", "O", "D", ("C1",), 0.5, 10),
            Route("B", "O", "D", ("C2",), 1.0, 10),
            Route("C", "O", "D", ("C1",), 1.8, 10),
        ),
        chokepoint_capacity_kbd={"C1": 1000.0, "C2": 1000.0, "C3": 1000.0},
        base_insurance=0.0,
        financing_rate=0.0,
    )


def test_scenarios_match_hand_computed_reroute_and_list_removed_lanes():
    out = site.scenarios(_two_strait_network(), {"X": 50.0})
    # C3 is on no route, so it gets no scenario.
    assert out["order"] == ["base", "c1", "c2"]
    base, c1, c2 = (out["items"][k] for k in out["order"])
    # Base: all 100 kb/d on A at 1.5 USD/bbl = 150,000 USD/day.
    assert base["daily_margin_usd"] == 150_000 and base["volume_kbd"] == 100.0
    assert base["same_as_base"] and base["removed_routes"] == []
    # C1 closed: A and C are gone, B carries 100 kb/d at 1.0 USD/bbl.
    assert c1["daily_margin_usd"] == 100_000 and c1["delta_daily_margin_usd"] == -50_000
    assert c1["stranded_kbd"] == 0.0 and not c1["same_as_base"]
    assert c1["removed_routes"] == ["A", "C"] and c1["removed_idle_routes"] == ["C"]
    assert {r["route"]: r["status"] for r in c1["routes"]} == {
        "A": "IDLE",
        "B": "ACTIVE",
        "C": "IDLE",
    }
    # C2 closed: the plan never used B, so nothing changes except the lost fallback lane.
    assert c2["same_as_base"] and c2["delta_daily_margin_usd"] == 0
    assert c2["removed_idle_routes"] == ["B"] and c2["feasible"]


def test_scenarios_cover_every_route_chokepoint_and_agree_with_hormuz_closure():
    network = default_network()
    prices = {"BRENT": 80.0, "WTI": 76.0}
    out = site.scenarios(network, prices)
    on_routes = {name for r in network.routes for name in r.chokepoints}
    assert {out["items"][k]["closed"][0] for k in out["order"][1:]} == on_routes
    hormuz = out["items"][site.scenario_id("Strait of Hormuz")]
    closure = site.hormuz_closure(network, prices)
    assert hormuz["daily_margin_usd"] == closure["closed"]["daily_margin_usd"]
    assert hormuz["stranded_kbd"] == closure["stranded_kbd"]
    assert out["label"] == "illustrative network, not a forecast"


def test_runs_returns_inclusive_index_ranges():
    mask = pd.Series([False, True, True, False, True, False, True, True])
    assert site._runs(mask) == [[1, 2], [4, 4], [6, 7]]
    assert site._runs(pd.Series([False, False])) == []


def _monitor_transits(days: int = 500) -> pd.DataFrame:
    """Hormuz: a 90/110 weekly zigzag, then 20 calls a day for the last 30 days."""
    dates = pd.date_range("2024-01-01", periods=days, freq="D")
    calls = [110.0 if (i // 7) % 2 else 90.0 for i in range(days)]
    calls[-30:] = [20.0] * 30
    return pd.DataFrame({"date": dates, "portname": "Strait of Hormuz", "n_total": calls})


def test_monitor_series_window_values_and_flag_reason():
    transits = _monitor_transits()
    out = site.monitor_series(transits, days=60)
    # Last day: 2024-01-01 + 499 days = 2025-05-14 (2024 is a leap year); 60 days end there.
    assert out["days"] == 60 and out["start"] == "2025-03-16"
    hormuz = out["series"]["Strait of Hormuz"]
    assert len(hormuz["ma7"]) == len(hormuz["baseline"]) == 60
    # The last seven raw values are all 20, so the last 7-day average is 20.
    assert hormuz["ma7"][-1] == 20.0
    latest = hormuz["latest"]
    assert latest["pct_condition"] == (latest["pct_change"] < out["pct_threshold"])
    assert latest["z_condition"] == (latest["zscore"] < out["z_threshold"])
    assert latest["flagged"] == (latest["pct_condition"] and latest["z_condition"])
    # A fall from about 100 to 20 against a zigzag baseline is flagged, and the flag shows as a run.
    assert latest["flagged"] and hormuz["flagged"][-1][1] == 59
    assert latest["spread"] * latest["zscore"] == pytest.approx(
        latest["ma7"] - latest["baseline"], abs=0.2
    )


def test_monitor_series_has_no_look_ahead():
    transits = _monitor_transits()
    before = site.monitor_series(transits, days=60)["series"]["Strait of Hormuz"]
    changed = transits.copy()
    changed.loc[changed.index[-1], "n_total"] = 500.0
    after = site.monitor_series(changed, days=60)["series"]["Strait of Hormuz"]
    assert after["ma7"][:-1] == before["ma7"][:-1]
    assert after["baseline"] == before["baseline"]  # the baseline is lagged by four weeks


def test_negative_print_day_is_placed_on_the_axis_with_the_next_day_carrying_the_move():
    series = {"start": "2020-04-01", "offsets": [0, 16, 19, 20], "loss": [1.0, 2.0, 0.5, 9.0]}
    out = site.negative_print_day(series, {"date": "2020-04-20", "value": -36.98}, 18.31)
    assert out["offset"] == 19 and out["wti"] == -36.98 and out["model_wti"] == 18.31
    assert out["in_test"] is True
    assert out["next_offset"] == 20 and out["next_loss"] == 9.0
    gap = {**series, "offsets": [0, 16, 20], "loss": [1.0, 2.0, 9.0]}
    dropped = site.negative_print_day(gap, {"date": "2020-04-20", "value": -36.98}, None)
    assert dropped["in_test"] is False and dropped["next_offset"] == 20


def test_portwatch_episode_compares_the_prior_year_with_the_lowest_complete_week():
    # 2024: 100 calls a day. From Mon 6 Jan 2025: weeks of 50, 20 and 40, then a two-day stub of 1.
    days = pd.date_range("2024-01-01", "2025-01-28", freq="D")
    calls = []
    for d in days:
        if d < pd.Timestamp("2025-01-06"):
            calls.append(100.0)
        elif d <= pd.Timestamp("2025-01-12"):
            calls.append(50.0)
        elif d <= pd.Timestamp("2025-01-19"):
            calls.append(20.0)
        elif d <= pd.Timestamp("2025-01-26"):
            calls.append(40.0)
        else:
            calls.append(1.0)  # 27-28 Jan: an incomplete week, ignored
    transits = pd.DataFrame({"date": days, "portname": "A", "n_total": calls})
    out = site.portwatch_episode(transits, "A", "2025-01-06", None)
    assert out["before_mean"] == 100.0  # 6 Jan 2024 to 5 Jan 2025, all 100
    assert out["lowest_week"] == {"value": 20.0, "week_end": "2025-01-19"}
    assert out["window"] == ["2025-01-06", "2025-01-28"]


def test_portwatch_episodes_on_the_committed_snapshot(tmp_path):
    settings = replace(load_settings(), offline=True, cache_dir=tmp_path)
    transits = DataService(settings).chokepoints()
    assert transits.source == "snapshot"
    eps = site.portwatch_episodes(transits.data)["episodes"]
    got = {
        e["chokepoint"]: (e["before_mean"], e["lowest_week"]["value"], e["lowest_week"]["week_end"])
        for group in eps.values()
        for e in group
    }
    assert got["Strait of Hormuz"] == (85.5, 1.4, "2026-03-22")
    assert got["Bab el-Mandeb Strait"] == (74.5, 26.3, "2024-07-28")
    assert got["Suez Canal"] == (73.8, 33.1, "2024-12-01")


def test_committed_site_json_wti_next_day_loss_matches_validation_json():
    data_dir = Path(site.__file__).resolve().parents[1] / "site" / "data"
    payload = json.loads((data_dir / "site.json").read_text(encoding="utf-8"))
    series = json.loads((data_dir / "validation.json").read_text(encoding="utf-8"))
    card = payload["crises"]["wti_2020"]["model_next_day"]
    assert card["date"] == "2020-04-21"
    assert card["loss_usd_m"] == series["negative_print"]["next_loss"]


def test_build_refuses_synthetic_inputs():
    prices = pd.DataFrame(
        {"BRENT": [80.0], "WTI": [76.0]}, index=pd.DatetimeIndex(["2024-01-02"], name="date")
    )
    fake = LoadResult(prices, "synthetic", "Synthetic demo data", None, (), "prices")
    with pytest.raises(ValueError, match="expected a snapshot"):
        site.build(fake, fake, pd.DataFrame(), {"passed": 1})


def test_build_end_to_end_on_small_snapshot_like_inputs():
    rng = np.random.default_rng(7)
    dates = pd.bdate_range("2019-01-01", "2022-12-30", name="date")
    steps = rng.normal(0.0, 0.02, size=(len(dates), 3)).cumsum(axis=0)
    prices = pd.DataFrame(
        np.exp(steps) * [70.0, 66.0, 3.0], index=dates, columns=["BRENT", "WTI", "HENRY_HUB"]
    )
    days = pd.date_range("2023-01-01", "2025-03-31", freq="D")
    transits = pd.DataFrame(
        [(d, name, 30) for d in days for name in ("Bab el-Mandeb Strait", "Suez Canal")]
        + [(d, "Strait of Hormuz", 90) for d in days],
        columns=["date", "portname", "n_total"],
    )
    fetched = datetime(2025, 4, 1, tzinfo=UTC)
    raw = pd.DataFrame({"date": ["2020-04-17", "2020-04-20"], "WTI": [18.31, -36.98]})
    payload = site.build(
        LoadResult(prices, "snapshot", "FRED", fetched, (), "prices"),
        LoadResult(transits, "snapshot", "IMF PortWatch", fetched, (), "chokepoints"),
        raw,
        {"passed": 10, "skipped": 1},
    )
    assert payload["as_of"] == {
        "prices": "2022-12-30",
        "transits": "2025-03-31",
        "snapshot_fetched": "2025-04-01",
    }
    assert payload["facts"]["risk_models"] == 5 and payload["facts"]["tests_passed"] == 10
    assert len(payload["validation"]["models"]) == 5
    assert {m["verdict"] for m in payload["validation"]["models"]} <= {"PASS", "REVIEW", "FAIL"}
    assert payload["hormuz_traffic"]["mean_2025"] == 90.0
    assert payload["crises"]["wti_2020"]["low"]["value"] == -36.98
    assert payload["scenarios"]["order"][0] == "base"
    assert payload["monitor_series"]["days"] == site.MONITOR_SERIES_DAYS
    series = payload["validation_series"]
    n = len(series["offsets"])
    assert len(series["loss"]) == n and series["offsets"][0] == 0
    for model in payload["validation"]["models"]:
        daily = series["models"][model["model"]]
        assert len(daily["var"]) == n
        # Exception days are the days with loss above VaR (rounding to 0.01m aside).
        assert len(daily["exceptions"]) == model["exceptions"]
        for i in daily["exceptions"]:
            assert series["loss"][i] >= daily["var"][i] - 0.01
    worst = series["extremes"]["largest_loss"]
    assert worst["loss"] == max(series["loss"])
    assert series["negative_print"]["date"] == "2020-04-20"
    assert payload["validation"]["rule"]["fail_level"] == 0.01
    nxt = payload["crises"]["wti_2020"]["model_next_day"]
    assert nxt is None or nxt["loss_usd_m"] == series["negative_print"]["next_loss"]
    assert set(payload["crises"]["portwatch"]["episodes"]) == {"red-sea", "hormuz"}


def test_chokepoint_status_compares_last_week_with_the_reference_year():
    year = _transits("A", [10.0] * 365, "2025-01-01")  # 2025: mean 10
    recent = _transits("A", [4, 4, 4, 4, 5, 5, 2], "2026-01-01")  # mean 4
    gappy = _transits("B", [10.0] * 365, "2025-01-01")
    gappy_recent = _transits("B", [1, 1, None, 1, 1, 1, 1], "2026-01-01")
    short = _transits("C", [10.0] * 100, "2025-01-01")
    short_recent = _transits("C", [1] * 7, "2026-01-01")
    frame = pd.concat([year, recent, gappy, gappy_recent, short, short_recent])
    out = site.chokepoint_status(frame, places=("A", "B", "C"))
    assert out["window"] == ["2026-01-01", "2026-01-07"]
    rows = {r["chokepoint"]: r["status"] for r in out["places"]}
    assert rows["A"] == {"recent_mean": 4.0, "reference_mean": 10.0, "change_pct": -60}
    assert rows["B"] is None  # a missing day in the recent window
    assert rows["C"] is None  # too little reference data


def test_chokepoint_status_uses_only_the_window_and_the_reference_year():
    older = _transits("A", [50.0] * 366, "2024-01-01")
    year = _transits("A", [10.0] * 365, "2025-01-01")
    recent = _transits("A", [4.0] * 7, "2026-01-01")
    frame = pd.concat([older, year, recent])
    base = site.chokepoint_status(frame, places=("A",))
    changed = frame.copy()
    changed.loc[changed["date"] < "2025-01-01", "n_total"] = 999.0
    assert site.chokepoint_status(changed, places=("A",)) == base
    assert base["places"][0]["status"]["reference_mean"] == 10.0
