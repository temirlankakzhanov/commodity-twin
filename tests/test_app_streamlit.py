"""Exercise the real Streamlit runtime (skipped when Streamlit is not installed)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]


def test_app_starts_without_exceptions(monkeypatch, tmp_path):
    monkeypatch.setenv("MTWIN_OFFLINE", "1")
    monkeypatch.setenv("MTWIN_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("MTWIN_SNAPSHOT_DIR", str(tmp_path / "snap"))
    app = AppTest.from_file(str(ROOT / "streamlit_app.py"), default_timeout=120).run()
    assert not app.exception, [e.value for e in app.exception]
    assert len(app.tabs) == 6
    assert any("SYNTHETIC" in w.value for w in app.warning)
    assert len(app.metric) >= 4


def test_demo_mode_switch_keeps_app_healthy(monkeypatch, tmp_path):
    monkeypatch.setenv("MTWIN_OFFLINE", "1")
    monkeypatch.setenv("MTWIN_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("MTWIN_SNAPSHOT_DIR", str(tmp_path / "snap"))
    app = AppTest.from_file(str(ROOT / "streamlit_app.py"), default_timeout=120).run()
    app.sidebar.radio[0].set_value("Synthetic demo").run()
    assert not app.exception
