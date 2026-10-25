# Methodology

All formulas use positive-loss conventions. Time is in trading days unless stated.

## 1. Data preparation

* **Prices** come from FRED daily spot series. Rows are sorted and de-duplicated (last value
  wins). Non-positive prices become missing: WTI printed -36.98 USD/bbl on 2020-04-20 and a log
  return is undefined there. Gaps of up to five observations are forward-filled (holidays);
  longer gaps drop the row. The 2020-04-20 row therefore stays in the sample with WTI equal to
  the previous price (18.31, from 2020-04-17), so WTI shows no move that day and the crash
  appears on 2020-04-21 as the net two-day move 18.31 -> 8.91. In general, the first valid
  print after a missing value carries the whole multi-day move.
* **Log returns** `r_t = ln(P_t / P_{t-1})`.
* **Book P&L** for signed USD notionals `N_k`: `PnL_t = sum_k N_k * (exp(r_{k,t}) - 1)`.

## 2. Volatility filters

Both return **one-step-ahead** forecasts: `sigma_t` uses information to `t-1` only.

* **EWMA (RiskMetrics)**: `v_t = lambda * v_{t-1} + (1 - lambda) * x_{t-1}^2`, `lambda = 0.94`,
  seeded with the mean square of the first 30 observations.
* **GARCH(1,1)**: `v_t = omega + alpha * x_{t-1}^2 + beta * v_{t-1}`, Gaussian quasi-maximum
  likelihood with variance targeting (`omega = (1 - alpha - beta) * sample variance`) so only
  `alpha`, `beta` are estimated (SLSQP, three starting points, `alpha + beta < 0.9999`).
  Parameters are fitted once on the first 750 observations and frozen, which keeps the test period
  out of sample.

## 3. VaR and ES models

Losses are `L_t = -x_t`. Every model forecasts the same dates, starting at
`max(window, garch_train)`.

| Model | VaR | ES |
| --- | --- | --- |
| Historical | empirical `alpha`-quantile of the last `window` losses | mean of losses at or above VaR |
| Normal (rolling) | `sigma * z_alpha`, sigma from the window's RMS return | `sigma * phi(z_alpha) / (1 - alpha)` |
| Normal (EWMA) | same with the EWMA sigma | same |
| Filtered HS | `sigma_t * q_alpha(L/sigma)` over the last `window` standardised losses | `sigma_t * tail mean of L/sigma` |

Filtered HS (Barone-Adesi et al.) rescales past standardised shocks by today's volatility, so
the forecast reacts to volatility clustering while keeping the empirical tail shape. It is
shown with EWMA and with GARCH(1,1) volatility.

## 4. Backtests

An **exception** is `L_t > VaR_t`. With `p = 1 - alpha`, `n` observations and `x` exceptions:

* **Kupiec (1995) POF**: `LR = -2 ln[(1-p)^(n-x) p^x] + 2 ln[(1-x/n)^(n-x) (x/n)^x]`,
  chi-squared(1). H0: exception probability equals `p`.
* **Christoffersen (1998) independence**: first-order Markov transition counts
  `n00, n01, n10, n11`; chi-squared(1). H0: exceptions do not cluster.
* **Conditional coverage**: sum of the two statistics, chi-squared(2).
* **Basel traffic light**: cumulative binomial probability of at most `x` exceptions under
  `p`: green below 95 %, yellow below 99.99 %, red above. For 250 days and `p = 1 %` this gives
  the regulatory 0-4 / 5-9 / 10+ zones. The lab applies it to the most recent 250 days.
* **ES Z2 (Acerbi-Szekely 2014)**: `Z2 = sum_t [L_t * 1(L_t > VaR_t) / ES_t] / (n (1-alpha)) - 1`.
  Expectation 0 for a correct model; **positive values mean ES is too low**. No p-value is
  reported because it needs Monte Carlo simulation under the model.

**Verdict rule** (a heuristic, not a regulatory standard): FAIL if the zone is red or the
conditional-coverage p-value is below 1 %; REVIEW if the zone is yellow or the Kupiec or
conditional-coverage p-value is below 5 %; otherwise PASS.

## 5. Trade network and optimiser

Unit margin of route `r` (USD/bbl):

```
margin_r = P_dest + diff_dest - (P_orig + diff_orig) - freight_r * m_freight
           - tolls_r - (insurance_base + sum_c war_risk_c) - P_orig * rate * days_r / 365
```

Decision variable `x_r >= 0` in kb/d. Maximise `sum_r margin_r * x_r * 1000` subject to
`sum_{r from o} x_r <= supply_o`, `sum_{r to d} x_r <= demand_d` and, for each chokepoint `c`,
`sum_{r via c} x_r <= capacity_c * factor_c` (factor 0 when closed). Solved with HiGHS.
**Shadow prices** are the dual values: the extra daily margin per extra kb/d of that limit, in
USD/bbl. They are tested against finite differences.

All network parameters are illustrative assumptions.

## 6. Book exposures and margin-at-risk

Barrels in transit are `flow * transit_days`, valued at the origin price. The desk is long the
origin benchmark and sells a `hedge_ratio` share short in the destination benchmark. A Brent-to-Brent
flow with full hedge has zero net exposure; a Houston-to-Rotterdam flow is a WTI-Brent spread.

**Margin-at-risk** bootstraps joint daily Brent/WTI log returns (default 20-day horizon, 5000
paths), re-prices the fixed plan and reports the confidence-quantile shortfall versus the base
margin and the average of the tail. Flows between same-benchmark ports have no flat-price
risk, so an independent normal basis shock (default 0.5 USD/bbl) is added per route.

## 7. Chokepoint monitor

For each chokepoint: `ma7 = 7-day mean of daily transit calls`; `baseline = mean of ma7` over a
180-day window lagged by 28 days (so a fresh disruption does not pull its own baseline down);
`z = (ma7 - baseline) / std(lagged ma7)`. Flag when `ma7/baseline - 1 < -25 %` and `z < -2`.
A flagged chokepoint becomes a scenario: closed when traffic is down more than 80 %, otherwise
capacity is scaled by the observed traffic ratio.

## 8. Known limitations

See the README. In short: illustrative network, single-period LP, assumed basis volatility,
low backtest power at 99 %, frozen GARCH parameters, and a monitor that adapts to long disruptions.
