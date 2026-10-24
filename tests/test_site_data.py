"""Landing-page data builder (scripts/build_site_data.py) and the raw WTI snapshot."""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest

from mtwin.data.service import LoadResult
from mtwin.data.transforms import clean_prices
from mtwin.trading import default_network
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
    assert "DCOILWTICO" in out["source"] and "FRED" in out["source"]


def test_committed_raw_wti_snapshot_has_the_negative_print_that_the_model_drops():
    raw = pd.read_csv(site.RAW_WTI)
    row = raw.loc[raw["date"] == "2020-04-20", "WTI"]
    assert float(row.iloc[0]) == -36.98
    cleaned = clean_prices(raw.assign(date=pd.to_datetime(raw["date"])).set_index("date"))
    assert (cleaned["WTI"] > 0).all()


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
