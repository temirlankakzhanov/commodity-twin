# Sample validation memo (synthetic data, unhedged Brent book of USD 50M)

- Data: SYNTHETIC demo data, not market data
- Test period: 2012-11-19 to 2026-01-30
- Confidence level: 99.0%; estimation window: 500 days; EWMA lambda: 0.94; GARCH training sample: 750 days
- Convention: VaR and ES are positive one-day losses; exception = loss > VaR

## Results

| Model | Obs | Exc | Expected | Kupiec p | Indep. p | CC p | Last 250d exc | Zone | ES Z2 | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Historical simulation | 3445 | 50 | 34.5 | 0.0126 | 0.7572 | 0.0425 | 11 | red | 0.583 | FAIL |
| Normal (rolling sigma) | 3445 | 65 | 34.5 | 0.0 | 0.5132 | 0.0 | 13 | red | 1.445 | FAIL |
| Normal (EWMA sigma) | 3445 | 58 | 34.5 | 0.0002 | 0.3545 | 0.0008 | 5 | yellow | 0.953 | FAIL |
| Filtered HS (EWMA) | 3445 | 44 | 34.5 | 0.1169 | 0.1296 | 0.0927 | 4 | green | 0.296 | PASS |
| Filtered HS (GARCH(1,1)) | 3445 | 46 | 34.5 | 0.0599 | 0.1536 | 0.0616 | 4 | green | 0.349 | PASS |

## Reading the table

- Kupiec tests whether the exception rate matches 1 - confidence.
- The independence test checks for clustering of exceptions.
- CC (conditional coverage) combines both tests.
- Basel zone uses the regulatory convention: exceptions in the most recent 250 days.
- ES Z2 above zero means Expected Shortfall is too low.
- Verdict rule: FAIL = red zone or CC p < 1 %; REVIEW = yellow zone or p < 5 %.

## Limitations

- Backtests on a single series have low power at 99 % confidence.
- GARCH parameters are estimated once and frozen; production models re-estimate.
- Results describe historical performance only and are not investment advice.
