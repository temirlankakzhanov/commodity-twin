"""The app's market-data cache must survive Streamlit reloading the ``mtwin`` modules.

After a source change (on Streamlit Community Cloud: every ``git pull`` after a push), Streamlit
evicts the project's modules from ``sys.modules`` and re-imports them, while ``st.cache_resource``
keeps objects built from the old classes. A cache that pickles its value then fails with
``PicklingError: ... it's not the same object as mtwin.data.service.LoadResult``.
"""

from __future__ import annotations

import importlib
import pickle
import sys

import pytest

pytest.importorskip("streamlit")


def _mtwin_modules() -> dict[str, object]:
    return {name: mod for name, mod in sys.modules.items() if name.split(".")[0] == "mtwin"}


def _evict_mtwin() -> None:
    for name in _mtwin_modules():
        del sys.modules[name]


@pytest.fixture
def offline(monkeypatch, tmp_path):
    """Offline settings with an empty cache; ``sys.modules`` is restored afterwards."""
    monkeypatch.setenv("MTWIN_OFFLINE", "1")
    monkeypatch.setenv("MTWIN_CACHE_DIR", str(tmp_path / "cache"))
    saved = _mtwin_modules()
    yield
    _evict_mtwin()
    sys.modules.update(saved)


def test_cached_market_survives_a_module_reload(offline):
    old = importlib.import_module("mtwin.ui.pages")
    old.get_service.clear()
    old.cached_market.clear()
    old.get_service()  # the server-wide service, built from the classes imported now
    _evict_mtwin()  # what Streamlit does on a source change
    new = importlib.import_module("mtwin.ui.pages")
    assert new is not old
    try:
        market = new.cached_market(True, 0)  # served by the old service: stale classes inside
        assert market.any_synthetic
    finally:
        new.cached_market.clear()
        new.get_service.clear()


@pytest.mark.parametrize("demo", [True, False])
def test_market_data_pickles_for_demo_and_snapshot(offline, demo):
    from mtwin.data import DataService
    from mtwin.ui.compute import load_market

    market = load_market(DataService(), demo=demo)
    sources = {r.source for r in (market.prices, market.chokepoints, market.macro)}
    assert sources == ({"synthetic"} if demo else {"snapshot"})
    restored = pickle.loads(pickle.dumps(market))
    assert restored.prices.data.equals(market.prices.data)
    assert restored.macro.label == market.macro.label
