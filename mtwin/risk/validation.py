"""Independent model validation: run several VaR/ES models through the same backtests."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import pandas as pd

from mtwin.risk.backtest import (
    basel_traffic_light,
    christoffersen_independence,
    conditional_coverage,
    es_z2,
    exceptions,
    kupiec_pof,
)
from mtwin.risk.var_models import MODEL_LABELS, ForecastConfig, forecast_var_es

BASEL_WINDOW = 250  # regulatory traffic-light window (trading days)

# Heuristic decision thresholds (documented in docs/methodology.md).
FAIL_LEVEL = 0.01
REVIEW_LEVEL = 0.05


@dataclass(frozen=True)
class ValidationResult:
    """Forecasts and the summary table for every validated model."""

    config: ForecastConfig
    forecasts: Mapping[str, pd.DataFrame]
    summary: pd.DataFrame


def verdict(zone: str, kupiec_p: float, cc_p: float) -> str:
    """Map test outcomes to PASS / REVIEW / FAIL.

    FAIL: red zone (last 250 days) or conditional-coverage p-value below 1 %.
    REVIEW: yellow zone or any of the Kupiec / conditional-coverage p-values below 5 %.
    PASS: otherwise.
    """
    if zone == "red" or cc_p < FAIL_LEVEL:
        return "FAIL"
    if zone == "yellow" or kupiec_p < REVIEW_LEVEL or cc_p < REVIEW_LEVEL:
        return "REVIEW"
    return "PASS"


def run_validation(
    pnl: pd.Series, models: Sequence[str], cfg: ForecastConfig | None = None
) -> ValidationResult:
    """Backtest each model on the same out-of-sample dates and tabulate the results."""
    cfg = cfg or ForecastConfig()
    p = 1.0 - cfg.alpha
    forecasts: dict[str, pd.DataFrame] = {}
    rows = []
    for model in models:
        fc = forecast_var_es(pnl, model, cfg)
        forecasts[model] = fc
        hits = exceptions(fc["loss"].to_numpy(), fc["var"].to_numpy())
        n_obs, n_exc = len(hits), int(hits.sum())
        pof = kupiec_pof(n_obs, n_exc, p)
        ind = christoffersen_independence(hits)
        cc = conditional_coverage(hits, p)
        recent = hits[-BASEL_WINDOW:]
        zone = basel_traffic_light(int(recent.sum()), len(recent), p)
        rows.append(
            {
                "model": MODEL_LABELS[model],
                "observations": n_obs,
                "exceptions": n_exc,
                "expected": round(n_obs * p, 1),
                "exception_rate_%": round(100.0 * n_exc / n_obs, 2),
                "kupiec_p": round(pof.pvalue, 4),
                "independence_p": round(ind.pvalue, 4),
                "cond_coverage_p": round(cc.pvalue, 4),
                "exc_last_250": int(recent.sum()),
                "basel_zone": zone,
                "avg_var_usd": float(fc["var"].mean()),
                "avg_es_usd": float(fc["es"].mean()),
                "es_z2": round(es_z2(fc["loss"], fc["var"], fc["es"], cfg.alpha), 3),
                "verdict": verdict(zone, pof.pvalue, cc.pvalue),
            }
        )
    return ValidationResult(cfg, forecasts, pd.DataFrame(rows))


def render_report(result: ValidationResult, *, title: str, data_label: str, period: str) -> str:
    """Render a bank-style validation memo in Markdown."""
    cfg = result.config
    summary = result.summary
    lines = [
        f"# {title}",
        "",
        f"- Data: {data_label}",
        f"- Test period: {period}",
        f"- Confidence level: {cfg.alpha:.1%}; estimation window: {cfg.window} days; "
        f"EWMA lambda: {cfg.lam}; GARCH training sample: {cfg.garch_train} days",
        "- Convention: VaR and ES are positive one-day losses; exception = loss > VaR",
        "",
        "## Results",
        "",
        "| Model | Obs | Exc | Expected | Kupiec p | Indep. p | CC p | Last 250d exc | Zone "
        "| ES Z2 | Verdict |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in summary.itertuples(index=False):
        lines.append(
            f"| {row.model} | {row.observations} | {row.exceptions} | {row.expected} | "
            f"{row.kupiec_p} | {row.independence_p} | {row.cond_coverage_p} | "
            f"{row.exc_last_250} | {row.basel_zone} | {row.es_z2} | {row.verdict} |"
        )
    lines += [
        "",
        "## Reading the table",
        "",
        "- Kupiec tests whether the exception rate matches 1 - confidence.",
        "- The independence test checks for clustering of exceptions.",
        "- CC (conditional coverage) combines both tests.",
        "- Basel zone uses the regulatory convention: exceptions in the most recent 250 days.",
        "- ES Z2 above zero means Expected Shortfall is too low.",
        "- Verdict rule: FAIL = red zone or CC p < 1 %; REVIEW = yellow zone or p < 5 %.",
        "",
        "## Limitations",
        "",
        "- Backtests on a single series have low power at 99 % confidence.",
        "- GARCH parameters are estimated once and frozen; production models re-estimate.",
        "- Results describe historical performance only and are not investment advice.",
    ]
    return "\n".join(lines)
