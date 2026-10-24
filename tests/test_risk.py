"""Returns, volatility filters and VaR/ES forecasters."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from scipy.stats import norm

from mtwin.data.synthetic import _garch_returns
from mtwin.risk.returns import log_returns, pnl_from_exposures
from mtwin.risk.var_models import MODEL_LABELS, ForecastConfig, forecast_var_es
from mtwin.risk.volatility import ewma_sigma, fit_garch11, garch11_sigma


def test_log_returns_rejects_non_positive_prices():
    with pytest.raises(ValueError):
        log_returns(pd.DataFrame({"A": [1.0, 0.0, 2.0]}))


def test_pnl_uses_exact_simple_return_and_sign_convention():
    returns = pd.DataFrame({"A": [np.log(1.10), np.log(0.90)], "B": [np.log(1.05), 0.0]})
    pnl = pnl_from_exposures({"A": 100.0, "B": -200.0}, returns)
    assert pnl.iloc[0] == pytest.approx(100 * 0.10 - 200 * 0.05)
    assert pnl.iloc[1] == pytest.approx(100 * -0.10)


def test_pnl_missing_factor_raises():
    with pytest.raises(KeyError):
        pnl_from_exposures({"X": 1.0}, pd.DataFrame({"A": [0.0]}))


def test_ewma_is_one_step_ahead_and_follows_recursion():
    x = pd.Series(np.r_[np.full(40, 0.01), 0.10, np.full(10, 0.01)])
    sigma = ewma_sigma(x, lam=0.9, seed_window=30)
    # The shock at index 40 must not affect sigma[40] (no look-ahead) but must affect sigma[41].
    assert sigma.iloc[40] == pytest.approx(0.01, rel=1e-6)
    expected = np.sqrt(0.9 * 0.01**2 + 0.1 * 0.10**2)
    assert sigma.iloc[41] == pytest.approx(expected, rel=1e-6)


def test_ewma_validates_inputs():
    with pytest.raises(ValueError):
        ewma_sigma(pd.Series(np.ones(100)), lam=1.0)
    with pytest.raises(ValueError):
        ewma_sigma(pd.Series(np.ones(10)), seed_window=30)


def test_garch_fit_recovers_parameters():
    x = _garch_returns(np.random.default_rng(1), 6000, 0.30, 0.08, 0.90, df=1e6)
    params = fit_garch11(x)
    assert params.alpha == pytest.approx(0.08, abs=0.03)
    assert params.beta == pytest.approx(0.90, abs=0.04)
    assert 0.9 < params.persistence < 1.0


def test_garch_fit_needs_enough_data():
    with pytest.raises(ValueError):
        fit_garch11(np.ones(100))


def test_garch_sigma_matches_recursion():
    x = pd.Series(np.random.default_rng(2).normal(0, 0.02, 400))
    params = fit_garch11(x)
    sigma = garch11_sigma(x, params)
    v = params.long_run_variance
    for t in range(1, 6):
        v = params.omega + params.alpha * x.iloc[t - 1] ** 2 + params.beta * v
        assert sigma.iloc[t] ** 2 == pytest.approx(v, rel=1e-9)


@pytest.fixture(scope="module")
def pnl(returns):
    return pnl_from_exposures({"BRENT": 50e6}, returns)


@pytest.mark.parametrize("model", list(MODEL_LABELS))
def test_forecasts_are_aligned_positive_and_ordered(pnl, model):
    cfg = ForecastConfig()
    fc = forecast_var_es(pnl, model, cfg)
    assert fc.index[0] == pnl.index[cfg.start]
    assert len(fc) == len(pnl) - cfg.start
    assert (fc["var"] > 0).all()
    assert (fc["es"] >= fc["var"] - 1e-6).all()
    assert np.allclose(fc["loss"], -pnl.iloc[cfg.start :])


def test_historical_var_is_the_empirical_quantile(pnl):
    cfg = ForecastConfig(alpha=0.99, window=500)
    fc = forecast_var_es(pnl, "historical", cfg)
    t = cfg.start + 10
    window = -pnl.iloc[t - cfg.window : t].to_numpy()
    assert fc["var"].iloc[10] == pytest.approx(np.quantile(window, 0.99))
    tail = window[window >= np.quantile(window, 0.99)]
    assert fc["es"].iloc[10] == pytest.approx(tail.mean())


def test_normal_var_formula(pnl):
    cfg = ForecastConfig(alpha=0.975, window=300, garch_train=300)
    fc = forecast_var_es(pnl, "normal", cfg)
    t = cfg.start
    sigma = np.sqrt(np.mean(pnl.iloc[t - 300 : t].to_numpy() ** 2))
    assert fc["var"].iloc[0] == pytest.approx(sigma * norm.ppf(0.975))
    assert fc["es"].iloc[0] == pytest.approx(sigma * norm.pdf(norm.ppf(0.975)) / 0.025)


def test_forecast_does_not_look_ahead(pnl):
    cfg = ForecastConfig()
    base = forecast_var_es(pnl, "fhs_ewma", cfg)
    changed = pnl.copy()
    changed.iloc[cfg.start + 50] *= 10  # modify one future observation
    other = forecast_var_es(changed, "fhs_ewma", cfg)
    assert np.allclose(base["var"].iloc[:50], other["var"].iloc[:50])
    assert not np.isclose(base["var"].iloc[51], other["var"].iloc[51])


def test_forecast_errors(pnl):
    with pytest.raises(ValueError, match="Unknown model"):
        forecast_var_es(pnl, "magic", ForecastConfig())
    with pytest.raises(ValueError, match="at least"):
        forecast_var_es(pnl.iloc[:600], "historical", ForecastConfig())
    with pytest.raises(ValueError):
        ForecastConfig(alpha=1.2)
