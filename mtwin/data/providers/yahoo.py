"""Optional Yahoo Finance provider (disabled by default).

``yfinance`` documents itself as a research and education tool and states that Yahoo's API is
intended for personal use only. A public deployment should therefore not rely on it or
redistribute its data. Enable it locally with ``MTWIN_ENABLE_YAHOO=1`` and ``pip install yfinance``.
"""

from __future__ import annotations

from collections.abc import Mapping

import pandas as pd

from mtwin.data.errors import ProviderError


class YahooProvider:
    """Download daily closing prices through the optional ``yfinance`` package."""

    name = "Yahoo Finance"

    def fetch_close(self, tickers: Mapping[str, str], start: str) -> pd.DataFrame:
        """Fetch closes for ``{name: ticker}`` and return a frame with one column per name."""
        try:
            import yfinance as yf
        except ImportError:
            raise ProviderError("yfinance is not installed") from None

        try:
            raw = yf.download(list(tickers.values()), start=start, progress=False, auto_adjust=True)
        except Exception as exc:  # yfinance raises a wide range of exception types
            raise ProviderError(f"yfinance download failed: {type(exc).__name__}") from None
        if raw is None or len(raw) == 0:
            raise ProviderError("yfinance returned no data")

        close = raw["Close"] if "Close" in raw.columns else raw
        if isinstance(close, pd.Series):
            close = close.to_frame(next(iter(tickers.values())))
        reverse = {ticker: name for name, ticker in tickers.items()}
        close = close.rename(columns=reverse)
        missing = [name for name in tickers if name not in close.columns]
        if missing:
            raise ProviderError(f"yfinance did not return: {', '.join(missing)}")
        close = close[list(tickers)]
        close.index = pd.DatetimeIndex(close.index).tz_localize(None)
        return close.rename_axis("date")
