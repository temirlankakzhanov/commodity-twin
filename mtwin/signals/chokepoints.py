"""Chokepoint traffic monitor (a deliberately simple global-value-chain signal).

For each chokepoint the 7-day moving average of transit calls is compared with a trailing
180-day baseline built from the same moving average and lagged by 28 days, so the baseline
excludes the most recent four weeks and is not dragged down by a fresh disruption. A chokepoint
is flagged when traffic is more than 25 % below baseline **and** the z-score is below -2.

Known limitation: after roughly six months of a persistent disruption the baseline adapts and
the flag clears, which is why the monitor is an early-warning signal and not a status board.
"""

from __future__ import annotations

import pandas as pd

SHORT_WINDOW = 7
BASELINE_WINDOW = 180
BASELINE_GAP = 28
PCT_THRESHOLD = -0.25
Z_THRESHOLD = -2.0


def compute_signals(transits: pd.DataFrame, value_col: str = "n_total") -> pd.DataFrame:
    """Daily monitor values per chokepoint.

    Args:
        transits: long frame with columns ``date``, ``portname`` and ``value_col``.

    Returns:
        Frame with ``date``, ``chokepoint``, ``ma7``, ``baseline``, ``pct_change``, ``zscore``
        and ``flagged``.
    """
    required = {"date", "portname", value_col}
    if not required <= set(transits.columns):
        raise ValueError(f"transits must contain columns {sorted(required)}")
    frames = []
    for name, group in transits.groupby("portname"):
        series = (
            group.assign(date=pd.to_datetime(group["date"]))
            .drop_duplicates("date")
            .set_index("date")[value_col]
            .astype(float)
            .sort_index()
            .asfreq("D")
        )
        ma = series.rolling(SHORT_WINDOW, min_periods=SHORT_WINDOW).mean()
        lagged = ma.shift(BASELINE_GAP)
        baseline = lagged.rolling(BASELINE_WINDOW, min_periods=BASELINE_WINDOW // 2).mean()
        spread = lagged.rolling(BASELINE_WINDOW, min_periods=BASELINE_WINDOW // 2).std()
        pct = ma / baseline - 1.0
        z = (ma - baseline) / spread.where(spread > 0)
        out = pd.DataFrame(
            {
                "date": series.index,
                "chokepoint": name,
                "ma7": ma.to_numpy(),
                "baseline": baseline.to_numpy(),
                "pct_change": pct.to_numpy(),
                "zscore": z.to_numpy(),
            }
        )
        out["flagged"] = (out["pct_change"] < PCT_THRESHOLD) & (out["zscore"] < Z_THRESHOLD)
        frames.append(out)
    if not frames:
        return pd.DataFrame(
            columns=["date", "chokepoint", "ma7", "baseline", "pct_change", "zscore", "flagged"]
        )
    return pd.concat(frames, ignore_index=True)


def latest_flags(signals: pd.DataFrame) -> pd.DataFrame:
    """Most recent monitor row per chokepoint (rows with a valid baseline only)."""
    valid = signals.dropna(subset=["pct_change", "zscore"])
    if valid.empty:
        return valid.reset_index(drop=True)
    idx = valid.groupby("chokepoint")["date"].idxmax()
    return valid.loc[idx].sort_values("pct_change").reset_index(drop=True)
