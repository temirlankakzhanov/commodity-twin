"""Shared fixtures. Everything is offline and deterministic."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from mtwin.config import Settings
from mtwin.data.synthetic import synthetic_prices
from mtwin.risk.returns import log_returns

FIXED_END = "2025-12-31"


@pytest.fixture(scope="session")
def prices() -> pd.DataFrame:
    """Synthetic BRENT/WTI/HENRY_HUB prices with a fixed end date."""
    return synthetic_prices("2010-01-01", end=FIXED_END)


@pytest.fixture(scope="session")
def returns(prices: pd.DataFrame) -> pd.DataFrame:
    """Daily log returns of the synthetic prices."""
    return log_returns(prices)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Settings that keep all files inside ``tmp_path`` and never touch the network."""
    return Settings(
        cache_dir=tmp_path / "cache",
        snapshot_dir=tmp_path / "snapshots",
        http_retries=0,
        http_backoff_s=0.0,
        provider_cooldown_s=300.0,
    )
