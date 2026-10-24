"""Backtest statistics and the validation verdict."""

from __future__ import annotations

import numpy as np
import pytest
from scipy.stats import chi2

from mtwin.risk.backtest import (
    basel_traffic_light,
    christoffersen_independence,
    conditional_coverage,
    es_z2,
    exceptions,
    kupiec_pof,
)
from mtwin.risk.validation import render_report, run_validation, verdict
from mtwin.risk.var_models import ForecastConfig


def test_kupiec_matches_hand_calculation():
    # 10 exceptions in 250 days at p = 1 %: LR = 2 * [10 ln(0.04/0.01) + 240 ln(0.96/0.99)]
    expected = 2 * (10 * np.log(0.04 / 0.01) + 240 * np.log(0.96 / 0.99))
    result = kupiec_pof(250, 10, 0.01)
    assert result.statistic == pytest.approx(expected)
    assert result.pvalue == pytest.approx(chi2.sf(expected, 1))
    assert result.rejects()


def test_kupiec_perfect_calibration_and_zero_exceptions():
    assert kupiec_pof(1000, 10, 0.01).statistic == pytest.approx(0.0, abs=1e-9)
    zero = kupiec_pof(250, 0, 0.01)
    assert zero.statistic == pytest.approx(-2 * 250 * np.log(0.99))


def test_kupiec_validates_inputs():
    with pytest.raises(ValueError):
        kupiec_pof(100, 101, 0.01)
    with pytest.raises(ValueError):
        kupiec_pof(100, 1, 1.5)


@pytest.mark.parametrize(
    ("exc", "zone"),
    [(0, "green"), (4, "green"), (5, "yellow"), (9, "yellow"), (10, "red"), (15, "red")],
)
def test_basel_zones_for_250_days_match_regulation(exc, zone):
    assert basel_traffic_light(exc, 250, 0.01) == zone


def test_independence_detects_clustering():
    rng = np.random.default_rng(0)
    iid = rng.random(5000) < 0.02
    clustered = np.zeros(5000, dtype=bool)
    clustered[1000:1050] = True
    clustered[3000:3050] = True
    assert christoffersen_independence(iid).pvalue > 0.01
    assert christoffersen_independence(clustered).pvalue < 1e-6


def test_conditional_coverage_is_sum_of_components():
    rng = np.random.default_rng(3)
    hits = rng.random(2000) < 0.03
    pof = kupiec_pof(2000, int(hits.sum()), 0.01)
    ind = christoffersen_independence(hits)
    cc = conditional_coverage(hits, 0.01)
    assert cc.statistic == pytest.approx(pof.statistic + ind.statistic)
    assert cc.df == 2


def test_es_z2_zero_for_correct_model_and_positive_when_es_too_low():
    rng = np.random.default_rng(5)
    alpha = 0.975
    losses = rng.standard_normal(200_000)
    var = np.full_like(losses, 1.959964)  # normal VaR at 97.5 %
    es_true = np.full_like(losses, 2.337803)  # normal ES at 97.5 %
    assert abs(es_z2(losses, var, es_true, alpha)) < 0.03
    assert es_z2(losses, var, es_true * 0.7, alpha) > 0.3


def test_exceptions_use_strict_inequality():
    hits = exceptions(np.array([1.0, 2.0, 3.0]), np.array([2.0, 2.0, 2.0]))
    assert hits.tolist() == [False, False, True]


@pytest.mark.parametrize(
    ("zone", "kp", "cc", "expected"),
    [
        ("green", 0.5, 0.5, "PASS"),
        ("yellow", 0.5, 0.5, "REVIEW"),
        ("green", 0.04, 0.5, "REVIEW"),
        ("green", 0.5, 0.03, "REVIEW"),
        ("red", 0.5, 0.5, "FAIL"),
        ("green", 0.5, 0.005, "FAIL"),
    ],
)
def test_verdict_rules(zone, kp, cc, expected):
    assert verdict(zone, kp, cc) == expected


def test_run_validation_table_and_report(returns):
    from mtwin.risk.returns import pnl_from_exposures

    pnl = pnl_from_exposures({"BRENT": 50e6}, returns)
    result = run_validation(pnl, ["historical", "fhs_ewma"], ForecastConfig())
    table = result.summary
    assert list(table["model"]) == ["Historical simulation", "Filtered HS (EWMA)"]
    assert (table["exceptions"] > 0).all()
    assert table["verdict"].isin(["PASS", "REVIEW", "FAIL"]).all()
    # filtering for volatility must beat plain historical simulation on this series
    assert table.loc[1, "kupiec_p"] >= table.loc[0, "kupiec_p"]
    memo = render_report(result, title="Memo", data_label="synthetic", period="x to y")
    assert "# Memo" in memo and "Filtered HS (EWMA)" in memo and "Limitations" in memo
