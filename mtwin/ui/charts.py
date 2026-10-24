"""Matplotlib figures. Every function is pure: data in, ``Figure`` out (no pyplot state).

Palette: first three slots of a validated categorical palette (blue, orange, aqua), applied in
a fixed order per entity so a series never changes colour between charts.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from matplotlib.figure import Figure

BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
RED, INK, MUTED, GRID = "#e34948", "#1f2328", "#59636e", "#d8dee4"
ENTITY_COLORS = {"BRENT": BLUE, "WTI": ORANGE, "HENRY_HUB": AQUA}
MAX_ROUTE_LABELS = 12


def _figure(width: float = 8.0, height: float = 3.6) -> tuple[Figure, object]:
    fig = Figure(figsize=(width, height), dpi=110, layout="constrained")
    ax = fig.subplots()
    ax.set_facecolor("white")
    ax.grid(axis="y", color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=8)
    return fig, ax


def _title(ax, title: str, subtitle: str | None = None) -> None:
    ax.set_title(
        title, loc="left", fontsize=10.5, color=INK, fontweight="bold", pad=14 if subtitle else 6
    )
    if subtitle:
        ax.text(0, 1.015, subtitle, transform=ax.transAxes, fontsize=8, color=MUTED, va="bottom")


def _legend(ax) -> None:
    handles, _ = ax.get_legend_handles_labels()
    if len(handles) > 1:
        ax.legend(frameon=False, fontsize=8, labelcolor=MUTED, loc="upper left", ncols=len(handles))


def price_chart(prices: pd.DataFrame, columns: tuple[str, ...] = ("BRENT", "WTI")) -> Figure:
    """Crude benchmark prices (Henry Hub is on a different scale, so it is excluded by default)."""
    fig, ax = _figure()
    for name in columns:
        if name in prices:
            ax.plot(
                prices.index,
                prices[name],
                color=ENTITY_COLORS.get(name, MUTED),
                linewidth=1.3,
                label=name,
            )
    ax.set_ylabel("USD per bbl", fontsize=8, color=MUTED)
    _title(ax, "Crude benchmark prices", "Daily, USD per barrel")
    _legend(ax)
    return fig


def flow_chart(flows: pd.DataFrame) -> Figure:
    """Optimal flow per route (only routes that carry volume)."""
    used = flows[flows["flow_kbd"] > 0].sort_values("flow_kbd")
    fig, ax = _figure(8.0, max(2.4, 0.42 * len(used) + 1.4))
    ax.grid(axis="x", color=GRID, linewidth=0.6)
    ax.grid(axis="y", visible=False)
    if used.empty:
        ax.text(
            0.5,
            0.5,
            "No profitable flows under this scenario",
            ha="center",
            va="center",
            color=MUTED,
            transform=ax.transAxes,
        )
        ax.set_xticks([])
        ax.set_yticks([])
    else:
        ax.barh(used["route"], used["flow_kbd"], color=BLUE, height=0.6)
        for y, value in enumerate(used["flow_kbd"]):
            ax.text(value, y, f" {value:,.0f}", va="center", fontsize=8, color=INK)
        ax.set_xlim(0, used["flow_kbd"].max() * 1.15)
    ax.set_xlabel("kb/d", fontsize=8, color=MUTED)
    _title(ax, "Optimal flows by route")
    return fig


def margin_waterfall_chart(economics_row: pd.Series) -> Figure:
    """Unit economics of a single route: gross spread, each cost item, resulting margin."""
    gross = float(economics_row["destination_price"] - economics_row["origin_price"])
    costs = [
        ("Freight", -economics_row["freight"]),
        ("Tolls", -economics_row["tolls"]),
        ("Insurance", -economics_row["insurance"]),
        ("Financing", -economics_row["financing"]),
    ]
    margin = float(economics_row["margin_usd_bbl"])
    labels = ["Gross spread", *[n for n, _ in costs], "Margin"]
    values = [gross, *[float(v) for _, v in costs], margin]
    fig, ax = _figure(8.0, 3.0)
    colors = [BLUE, *([ORANGE] * len(costs)), BLUE if margin >= 0 else RED]
    ax.bar(labels, values, color=colors, width=0.6)
    span = max(abs(v) for v in values) or 1.0
    for x, v in enumerate(values):
        ax.text(
            x,
            v + (0.03 * span if v >= 0 else -0.03 * span),
            f"{v + 0.0:+.2f}",
            ha="center",
            va="bottom" if v >= 0 else "top",
            fontsize=8,
            color=INK,
        )
    ax.axhline(0, color=MUTED, linewidth=0.8)
    ax.set_ylim(min([*values, 0.0]) - 0.2 * span, max([*values, 0.0]) + 0.2 * span)
    ax.set_ylabel("USD per bbl", fontsize=8, color=MUTED)
    _title(
        ax,
        f"Unit margin build-up: {economics_row['route']}",
        "Destination price minus origin price, less each cost item",
    )
    return fig


def scenario_chart(table: pd.DataFrame) -> Figure:
    """Daily margin per scenario, base case highlighted."""
    fig, ax = _figure(8.0, max(2.4, 0.5 * len(table) + 1.4))
    ax.grid(axis="x", color=GRID, linewidth=0.6)
    ax.grid(axis="y", visible=False)
    names = table["scenario"].tolist()[::-1]
    values = (table["daily_margin_usd"] / 1e6).tolist()[::-1]
    colors = [BLUE if i == len(names) - 1 else ORANGE for i in range(len(names))]
    ax.barh(names, values, color=colors, height=0.6)
    for y, v in enumerate(values):
        ax.text(v, y, f" {v:,.2f}", va="center", fontsize=8, color=INK)
    ax.set_xlim(0, max([*values, 0.0]) * 1.18 or 1.0)
    ax.set_xlabel("Daily margin, USD million", fontsize=8, color=MUTED)
    _title(ax, "Daily margin by scenario", "Base case in blue")
    return fig


def margin_distribution_chart(
    simulated: np.ndarray, base: float, var: float, confidence: float
) -> Figure:
    """Histogram of simulated daily margin with the base and VaR levels marked."""
    fig, ax = _figure(8.0, 3.2)
    spread = float(np.ptp(simulated))
    ax.hist(simulated / 1e6, bins=60 if spread > 0 else 1, color=BLUE, alpha=0.85)
    ax.axvline(base / 1e6, color=INK, linewidth=1.2)
    ax.axvline((base - var) / 1e6, color=RED, linewidth=1.4)
    top = ax.get_ylim()[1]
    ax.text(base / 1e6, top, " base", fontsize=8, color=INK, va="top")
    ax.text(
        (base - var) / 1e6,
        top,
        f"{confidence:.0%} margin-at-risk ",
        fontsize=8,
        color=RED,
        va="top",
        ha="right",
    )
    ax.set_xlabel("Daily margin of the fixed plan, USD million", fontsize=8, color=MUTED)
    ax.set_yticks([])
    _title(ax, "Simulated margin after a market move", "Bootstrap of historical Brent/WTI returns")
    return fig


def var_backtest_chart(forecast: pd.DataFrame, model_label: str) -> Figure:
    """Realised loss against VaR and ES, with exceptions marked."""
    fig, ax = _figure(8.0, 3.8)
    loss = forecast["loss"] / 1e6
    ax.plot(forecast.index, loss, color=MUTED, linewidth=0.5, alpha=0.7, label="Realised loss")
    ax.plot(forecast.index, forecast["var"] / 1e6, color=BLUE, linewidth=1.2, label="VaR")
    ax.plot(forecast.index, forecast["es"] / 1e6, color=ORANGE, linewidth=1.0, label="ES")
    hits = forecast["loss"] > forecast["var"]
    ax.scatter(
        forecast.index[hits],
        loss[hits],
        s=14,
        color=RED,
        zorder=3,
        label=f"Exceptions ({int(hits.sum())})",
    )
    ax.set_ylabel("USD million", fontsize=8, color=MUTED)
    _title(ax, f"Backtest: {model_label}", "Positive values are losses")
    _legend(ax)
    return fig


def chokepoint_chart(signals: pd.DataFrame, chokepoint: str) -> Figure:
    """7-day traffic against its baseline, with flagged days marked."""
    data = signals[signals["chokepoint"] == chokepoint].dropna(subset=["ma7"])
    fig, ax = _figure(8.0, 3.2)
    ax.plot(data["date"], data["ma7"], color=BLUE, linewidth=1.3, label="7-day average")
    ax.plot(
        data["date"], data["baseline"], color=MUTED, linewidth=1.0, linestyle="--", label="Baseline"
    )
    flagged = data[data["flagged"]]
    if not flagged.empty:
        ax.scatter(flagged["date"], flagged["ma7"], s=10, color=RED, zorder=3, label="Flagged")
    ax.set_ylabel("Transit calls per day", fontsize=8, color=MUTED)
    _title(ax, f"{chokepoint}: daily transit calls", "Flag: > 25 % below baseline and z-score < -2")
    _legend(ax)
    return fig
