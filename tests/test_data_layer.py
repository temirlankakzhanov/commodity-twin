"""Cache, transforms, HTTP client, providers and the fallback chain."""

from __future__ import annotations

import json
import math
import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer

import numpy as np
import pandas as pd
import pytest

from mtwin.config import Settings
from mtwin.data import DataService, ProviderError
from mtwin.data.cache import ParquetCache
from mtwin.data.errors import DataError
from mtwin.data.http import HttpClient, build_session
from mtwin.data.providers import FredProvider, PortWatchProvider, WorldBankProvider
from mtwin.data.providers.fred import parse_fred_api_json, parse_fred_csv
from mtwin.data.providers.portwatch import parse_portwatch
from mtwin.data.providers.worldbank import parse_worldbank
from mtwin.data.transforms import clean_prices

# ------------------------------------------------------------------ transforms


def _raw_prices(n: int = 300) -> pd.DataFrame:
    idx = pd.bdate_range("2020-01-01", periods=n)
    return pd.DataFrame({"WTI": np.linspace(50, 60, n), "BRENT": np.linspace(55, 65, n)}, index=idx)


def test_clean_prices_turns_negative_wti_into_missing_then_fills():
    raw = _raw_prices()
    raw.iloc[100, 0] = -36.98
    raw.iloc[101, 0] = np.nan
    clean = clean_prices(raw)
    assert (clean > 0).all().all()
    assert clean.iloc[100, 0] == pytest.approx(raw.iloc[99, 0])  # carried forward, not interpolated
    assert len(clean) == len(raw)


def test_clean_prices_limits_ffill_and_dedupes():
    raw = _raw_prices()
    raw.iloc[50:60, 0] = np.nan  # a 10-day gap exceeds the 5-day limit
    clean = clean_prices(raw)
    assert len(clean) == len(raw) - 5
    dup = pd.concat([raw, raw.iloc[[3]]])
    assert not clean_prices(dup).index.duplicated().any()


def test_clean_prices_requires_enough_rows():
    with pytest.raises(DataError):
        clean_prices(_raw_prices(10))


# ------------------------------------------------------------------ cache


def test_cache_roundtrip_preserves_index_and_dtypes(tmp_path):
    cache = ParquetCache(tmp_path, ttl_hours=1)
    df = _raw_prices(20).rename_axis("date")
    cache.put("prices/v1", df, source="unit-test")
    entry = cache.get("prices/v1")
    assert entry is not None and entry.fresh and entry.source == "unit-test"
    pd.testing.assert_frame_equal(entry.data, df, check_freq=False, check_index_type=False)
    assert isinstance(entry.data.index, pd.DatetimeIndex)


def test_cache_roundtrip_for_frame_without_index(tmp_path):
    cache = ParquetCache(tmp_path, ttl_hours=1)
    df = pd.DataFrame(
        {"date": pd.date_range("2024-01-01", periods=3), "x": [1, 2, 3], "name": list("abc")}
    )
    cache.put("k", df)
    pd.testing.assert_frame_equal(cache.get("k").data, df)


def test_cache_ttl_and_allow_stale(tmp_path):
    clock = {"now": datetime(2026, 1, 1, tzinfo=UTC)}
    cache = ParquetCache(tmp_path, ttl_hours=2, now=lambda: clock["now"])
    cache.put("k", _raw_prices(5))
    assert cache.get("k").fresh
    clock["now"] += timedelta(hours=3)
    assert cache.get("k").fresh is False
    assert cache.get("k", allow_stale=False) is None


def test_cache_infinite_ttl_is_always_fresh(tmp_path):
    clock = {"now": datetime(2026, 1, 1, tzinfo=UTC)}
    cache = ParquetCache(tmp_path, ttl_hours=math.inf, now=lambda: clock["now"])
    cache.put("k", _raw_prices(5))
    clock["now"] += timedelta(days=3650)
    assert cache.get("k").fresh


def test_cache_corrupt_file_is_treated_as_missing(tmp_path):
    cache = ParquetCache(tmp_path, ttl_hours=1)
    cache.put("k", _raw_prices(5))
    data_file = next(p for p in tmp_path.iterdir() if p.suffix in {".parquet", ".gz"})
    data_file.write_bytes(b"not a real file")
    assert cache.get("k") is None


def test_cache_missing_key_and_clear(tmp_path):
    cache = ParquetCache(tmp_path, ttl_hours=1)
    assert cache.get("nope") is None
    cache.put("k", _raw_prices(5))
    cache.clear()
    assert cache.get("k") is None


def test_cache_keys_with_odd_characters_do_not_collide(tmp_path):
    cache = ParquetCache(tmp_path, ttl_hours=1)
    cache.put("a/b", pd.DataFrame({"x": [1]}))
    cache.put("a_b", pd.DataFrame({"x": [2]}))
    assert cache.get("a/b").data["x"].iloc[0] == 1
    assert cache.get("a_b").data["x"].iloc[0] == 2


# ------------------------------------------------------------------ parsers


def test_parse_fred_csv_accepts_both_date_headers_and_missing_markers():
    for header in ("DATE", "observation_date"):
        text = f"{header},DCOILWTICO\n2024-01-02,70.1\n2024-01-03,.\n2024-01-04,71.5\n"
        series = parse_fred_csv(text, "DCOILWTICO")
        assert series.tolist() == [70.1, 71.5]
        assert isinstance(series.index, pd.DatetimeIndex)


@pytest.mark.parametrize("body", ["", "<html>maintenance</html>", "DATE\n2024-01-01\n"])
def test_parse_fred_csv_rejects_bad_bodies(body):
    with pytest.raises(ProviderError):
        parse_fred_csv(body, "X")


def test_parse_fred_api_json_and_error_payload():
    payload = {
        "observations": [
            {"date": "2024-01-02", "value": "70.1"},
            {"date": "2024-01-03", "value": "."},
        ]
    }
    assert parse_fred_api_json(payload, "X").tolist() == [70.1]
    with pytest.raises(ProviderError, match="Bad Request"):
        parse_fred_api_json({"error_code": 400, "error_message": "Bad Request"}, "X")


def test_parse_worldbank_drops_nulls_and_reports_pages():
    payload = [
        {"page": 1, "pages": 3, "total": 4},
        [
            {
                "countryiso3code": "KAZ",
                "country": {"id": "KZ", "value": "Kazakhstan"},
                "indicator": {"id": "NY.GDP.MKTP.CD"},
                "date": "2023",
                "value": 262.6e9,
            },
            {
                "countryiso3code": "KAZ",
                "country": {"id": "KZ", "value": "Kazakhstan"},
                "indicator": {"id": "NY.GDP.MKTP.CD"},
                "date": "2024",
                "value": None,
            },
        ],
    ]
    frame, pages = parse_worldbank(payload)
    assert pages == 3 and len(frame) == 1 and frame["year"].iloc[0] == 2023
    with pytest.raises(ProviderError):
        parse_worldbank([{"message": [{"id": "120"}]}])
    with pytest.raises(ProviderError):
        parse_worldbank({"oops": 1})


def test_parse_portwatch_accepts_iso_and_epoch_dates():
    def payload(date_value):
        return {
            "features": [
                {
                    "attributes": {
                        "date": date_value,
                        "portid": "p1",
                        "portname": "Suez Canal",
                        "n_total": 40,
                        "n_tanker": 10,
                    }
                }
            ]
        }

    iso = parse_portwatch(payload("2025-03-01"))
    epoch = parse_portwatch(payload(1740787200000))
    assert iso["date"].iloc[0] == pd.Timestamp("2025-03-01")
    assert epoch["date"].iloc[0] == pd.Timestamp("2025-03-01")
    assert parse_portwatch({"features": []}).empty
    with pytest.raises(ProviderError):
        parse_portwatch({"error": {"code": 400}})


# ------------------------------------------------------------------ HTTP client


class _Response:
    def __init__(self, status=200, text="", payload=None):
        self.status_code, self.text, self._payload = status, text, payload

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class _Session:
    def __init__(self, *responses_or_errors):
        self.queue = list(responses_or_errors)
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params, timeout))
        item = self.queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def test_http_client_errors_never_leak_query_strings(settings):
    import requests

    leaky = requests.ConnectionError("HTTPSConnectionPool: /api?api_key=SECRET123 failed")
    client = HttpClient(settings, _Session(leaky, _Response(500), _Response(200, payload=None)))
    for call in (client.get_text, client.get_text, client.get_json):
        with pytest.raises(ProviderError) as info:
            call("https://example.org/api?api_key=SECRET123", {"api_key": "SECRET123"})
        assert "SECRET123" not in str(info.value)


def test_http_client_returns_text_and_json(settings):
    client = HttpClient(settings, _Session(_Response(text="hello"), _Response(payload={"a": 1})))
    assert client.get_text("https://x.test") == "hello"
    assert client.get_json("https://x.test") == {"a": 1}


class _FlakyHandler(BaseHTTPRequestHandler):
    hits = 0

    def do_GET(self):
        type(self).hits += 1
        if type(self).hits <= 2:
            self.send_response(503)
            self.end_headers()
            return
        body = json.dumps({"ok": True}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # silence the test server
        return None


def test_real_session_retries_transient_503(monkeypatch, tmp_path):
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    _FlakyHandler.hits = 0
    server = HTTPServer(("127.0.0.1", 0), _FlakyHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        settings = Settings(
            cache_dir=tmp_path, snapshot_dir=tmp_path, http_retries=3, http_backoff_s=0.0
        )
        client = HttpClient(settings, build_session(settings))
        assert client.get_json(f"http://127.0.0.1:{server.server_port}/x") == {"ok": True}
        assert _FlakyHandler.hits == 3
    finally:
        server.shutdown()
        server.server_close()


# ------------------------------------------------------------------ providers + service


class _StubFred:
    name = "FRED"

    def __init__(self, fail=False):
        self.fail, self.calls = fail, 0

    def fetch_series(self, series_id, start=None, end=None):
        self.calls += 1
        if self.fail:
            raise ProviderError("down")
        idx = pd.bdate_range("2015-01-01", periods=600)
        base = {"DCOILBRENTEU": 70.0, "DCOILWTICO": 66.0, "DHHNGSP": 3.0}[series_id]
        return pd.Series(base + np.sin(np.arange(600) / 20), index=idx, name=series_id)


class _StubPortWatch:
    name = "IMF PortWatch"

    def __init__(self, fail=False):
        self.fail = fail

    def fetch_chokepoints(self, names, start, max_rows_per_name=0):
        if self.fail:
            raise ProviderError("down")
        from mtwin.data.synthetic import synthetic_chokepoints

        return synthetic_chokepoints(names, str(start))


class _StubWorldBank:
    name = "World Bank"

    def fetch_indicators(self, countries, indicators, start_year, end_year):
        raise ProviderError("down")


def _service(settings, fred=None, portwatch=None, clock=None):
    return DataService(
        settings,
        fred=fred or _StubFred(),
        portwatch=portwatch or _StubPortWatch(),
        worldbank=_StubWorldBank(),
        monotonic=clock or (lambda: 0.0),
    )


def test_service_live_then_cache_hit_avoids_second_call(settings):
    fred = _StubFred()
    svc = _service(settings, fred=fred)
    first = svc.prices()
    assert first.source == "live" and first.is_real
    assert list(first.data.columns) == ["BRENT", "WTI", "HENRY_HUB"]
    calls = fred.calls
    second = svc.prices()
    assert second.source == "cache" and fred.calls == calls


def test_service_serves_stale_cache_when_provider_fails(settings):
    svc = _service(settings)
    svc.prices()
    # same cache directory, expired TTL, provider now down
    stale_settings = Settings(**{**settings.__dict__, "cache_ttl_hours": 0.0})
    svc2 = _service(stale_settings, fred=_StubFred(fail=True))
    result = svc2.prices()
    assert result.source == "stale-cache"
    assert any("stale" in n.lower() for n in result.notes)


def test_service_falls_back_to_snapshot_then_synthetic(settings):
    seed = _service(settings)
    live = seed.prices()
    seed.write_snapshot(live)
    down = _service(
        Settings(**{**settings.__dict__, "cache_dir": settings.cache_dir / "other"}),
        fred=_StubFred(fail=True),
    )
    assert down.prices().source == "snapshot"
    nothing = _service(
        Settings(
            **{
                **settings.__dict__,
                "cache_dir": settings.cache_dir / "x",
                "snapshot_dir": settings.snapshot_dir / "y",
            }
        ),
        fred=_StubFred(fail=True),
    )
    result = nothing.prices()
    assert result.source == "synthetic" and not result.is_real
    assert (result.data > 0).all().all()


def test_service_cooldown_prevents_hammering_a_failing_provider(settings):
    fred = _StubFred(fail=True)
    now = {"t": 0.0}
    svc = _service(settings, fred=fred, clock=lambda: now["t"])
    svc.prices()
    first_calls = fred.calls
    svc.prices()
    assert fred.calls == first_calls  # still cooling down
    now["t"] = 10_000.0
    svc.prices()
    assert fred.calls > first_calls


def test_service_offline_and_force_synthetic(settings):
    fred = _StubFred()
    offline = Settings(**{**settings.__dict__, "offline": True})
    assert _service(offline, fred=fred).prices().source == "synthetic"
    assert fred.calls == 0
    assert _service(settings, fred=fred).prices(force_synthetic=True).source == "synthetic"
    assert fred.calls == 0


def test_service_chokepoints_and_macro_fallbacks(settings):
    svc = _service(settings)
    assert svc.chokepoints().source == "live"
    macro = svc.macro()
    assert macro.source == "synthetic"
    assert {"country_iso3", "indicator", "year", "value"} <= set(macro.data.columns)


def test_snapshot_refuses_synthetic(settings):
    svc = _service(settings)
    with pytest.raises(ValueError):
        svc.write_snapshot(svc.prices(force_synthetic=True))


def test_real_providers_use_the_documented_endpoints(settings):
    seen = []

    class Recorder:
        def get_text(self, url, params=None):
            seen.append((url, params))
            return "DATE,DCOILWTICO\n2024-01-02,70.1\n2024-01-03,71.0\n"

        def get_json(self, url, params=None):
            seen.append((url, params))
            if "arcgis" in url.lower() or "portwatch" in url.lower():
                return {
                    "features": [
                        {
                            "attributes": {
                                "date": "2024-01-02",
                                "portid": "p",
                                "portname": "Suez Canal",
                                "n_total": 40,
                                "n_tanker": 9,
                            }
                        }
                    ]
                }
            return [
                {"pages": 1},
                [
                    {
                        "countryiso3code": "KAZ",
                        "country": {"id": "KZ", "value": "K"},
                        "indicator": {"id": "I"},
                        "date": "2023",
                        "value": 1.0,
                    }
                ],
            ]

    http = Recorder()
    assert FredProvider(http).fetch_series("DCOILWTICO", start="2024-01-01").tolist() == [
        70.1,
        71.0,
    ]
    assert seen[0][1] == {"id": "DCOILWTICO", "cosd": "2024-01-01"}
    keyed = FredProvider(http, api_key="k")
    with pytest.raises(ProviderError):  # the recorder returns CSV-shaped data for the API path
        keyed.fetch_series("X")
    pw = PortWatchProvider(http).fetch_chokepoints(["Suez Canal"], datetime(2024, 1, 1).date())
    assert pw["portname"].iloc[0] == "Suez Canal"
    wb = WorldBankProvider(http).fetch_indicator(["KAZ"], "I", 2020, 2024)
    assert wb["year"].iloc[0] == 2023
