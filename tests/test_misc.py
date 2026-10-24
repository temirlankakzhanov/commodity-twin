"""Configuration, catalogue, optional storage back-ends and the Yahoo fallback."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from mtwin.config import PROJECT_ROOT, Settings, load_settings
from mtwin.data import DataService, ProviderError
from mtwin.data.cache import ParquetCache
from mtwin.data.catalog import describe_cache
from mtwin.data.providers import YahooProvider


def test_load_settings_defaults_and_overrides(monkeypatch, tmp_path):
    for name in ("MTWIN_CACHE_DIR", "MTWIN_OFFLINE", "MTWIN_ENABLE_YAHOO", "FRED_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    default = load_settings()
    assert default.cache_dir == PROJECT_ROOT / ".cache" / "mtwin"
    assert default.snapshot_dir == PROJECT_ROOT / "data" / "snapshots"
    assert not default.offline and not default.enable_yahoo and default.fred_api_key is None

    monkeypatch.setenv("MTWIN_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("MTWIN_OFFLINE", "yes")
    monkeypatch.setenv("MTWIN_ENABLE_YAHOO", "0")
    monkeypatch.setenv("MTWIN_HTTP_RETRIES", "5")
    monkeypatch.setenv("FRED_API_KEY", "abc")
    custom = load_settings()
    assert custom.cache_dir == tmp_path and custom.offline and not custom.enable_yahoo
    assert custom.http_retries == 5 and custom.fred_api_key == "abc"


def test_describe_cache_lists_datasets(tmp_path):
    cache = ParquetCache(tmp_path, ttl_hours=1)
    frame = pd.DataFrame(
        {"BRENT": [70.0, 71.0, 72.0]}, index=pd.bdate_range("2024-01-01", periods=3)
    )
    cache.put("prices", frame.rename_axis("date"), source="unit-test")
    catalogue = describe_cache(Path(tmp_path))
    assert catalogue.loc[0, "dataset"] == "prices"
    assert catalogue.loc[0, "rows"] == 3
    assert catalogue.loc[0, "first_date"] == "2024-01-01"
    assert catalogue.loc[0, "last_date"] == "2024-01-03"
    assert describe_cache(tmp_path / "missing").empty


@pytest.mark.skipif(importlib.util.find_spec("pyarrow") is None, reason="pyarrow not installed")
def test_parquet_backend_roundtrip(tmp_path):
    cache = ParquetCache(tmp_path, ttl_hours=1)
    frame = pd.DataFrame(
        {"x": np.arange(5.0), "when": pd.date_range("2024-01-01", periods=5)}
    ).set_index("when")
    cache.put("k", frame, source="parquet")
    assert any(p.suffix == ".parquet" for p in tmp_path.iterdir())
    pd.testing.assert_frame_equal(cache.get("k").data, frame, check_freq=False)


@pytest.mark.skipif(importlib.util.find_spec("duckdb") is None, reason="duckdb not installed")
def test_catalogue_uses_duckdb_for_parquet(tmp_path):
    cache = ParquetCache(tmp_path, ttl_hours=1)
    frame = pd.DataFrame({"v": [1.0, 2.0]}, index=pd.bdate_range("2024-03-01", periods=2))
    cache.put("k", frame.rename_axis("date"))
    assert describe_cache(tmp_path).loc[0, "last_date"] == "2024-03-04"


@pytest.mark.skipif(importlib.util.find_spec("yfinance") is not None, reason="yfinance installed")
def test_yahoo_provider_reports_missing_dependency():
    with pytest.raises(ProviderError, match="not installed"):
        YahooProvider().fetch_close({"BRENT": "BZ=F"}, "2020-01-01")


class _DownFred:
    name = "FRED"

    def fetch_series(self, *args, **kwargs):
        raise ProviderError("down")


class _StubYahoo:
    name = "Yahoo Finance"

    def fetch_close(self, tickers, start):
        idx = pd.bdate_range("2018-01-01", periods=400)
        return pd.DataFrame(
            {name: 50.0 + i + np.arange(400) * 0.01 for i, name in enumerate(tickers)}, index=idx
        )


def test_yahoo_is_used_only_when_enabled(settings):
    off = DataService(settings, fred=_DownFred(), yahoo=_StubYahoo())
    assert off.prices().source == "synthetic"
    on_settings = Settings(
        **{**settings.__dict__, "enable_yahoo": True, "cache_dir": settings.cache_dir / "y"}
    )
    on = DataService(on_settings, fred=_DownFred(), yahoo=_StubYahoo())
    result = on.prices()
    assert result.source == "live" and result.label == "Yahoo Finance"
