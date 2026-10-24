# CLAUDE.md

Guidance for Claude Code (and other coding agents) working in this repository.

## Project

Commodity Merchant Digital Twin: a Streamlit app that (1) optimises crude-oil flows over a
route network, (2) stress-tests chokepoint closures using IMF PortWatch traffic, and (3)
validates VaR/ES models with formal backtests. It is a public portfolio project.

- Owner communication: **Russian**. Code, comments, docstrings, UI text, docs, commit messages,
  README: **English** (professional, institutional tone).
- Quality and correctness matter more than feature count.

## Commands

```bash
make install     # venv + dependencies + pre-commit
make run         # streamlit run streamlit_app.py
make test        # pytest (offline, deterministic)
make lint        # ruff check + ruff format --check
make format      # ruff check --fix + ruff format
make check       # lint + test: run before saying "done"
make fetch       # download real data into .cache/ (network)
make snapshot    # fetch and write data/snapshots/ (network; commit the result)
make figures     # regenerate docs/img from synthetic data
```

Always run `make check` after code changes and report the actual result. Never claim a command
passed without running it.

## Architecture

```
ui (charts, compute, pages) -> risk, trading, signals -> data
```

- `mtwin/data`: http (retries, secret-safe errors), cache (Parquet or csv.gz, TTL), providers
  (fred, worldbank, portwatch, yahoo), service (fallback chain), synthetic, catalog (DuckDB).
- `mtwin/risk`: returns, volatility (EWMA, GARCH), var_models, backtest, validation.
- `mtwin/trading`: network, optimizer (LP), scenarios, book (exposures, margin-at-risk).
- `mtwin/signals`: chokepoint traffic monitor.
- `mtwin/ui`: matplotlib figures (pure), framework-free compute helpers, Streamlit pages.

Rules:

1. Dependencies point downwards only. Only `mtwin/ui/pages.py` and `streamlit_app.py` import
   `streamlit`.
2. Network I/O lives only in `mtwin/data/http.py` and the providers. Everything else is pure.
3. New data sources are new classes in `mtwin/data/providers/` plus a parser function that is
   tested with a fixture payload. Wire them in through `DataService`, never directly in the UI.
4. Every dataset must resolve through the fallback chain
   (fresh cache, live, stale cache, snapshot, synthetic). The UI must label synthetic data.

## Conventions

- Python 3.11+. Type hints on public functions. Google-style docstrings. `from __future__
  import annotations`.
- Formatting and lint: ruff (line length 100). Do not add other formatters.
- Finance conventions: log returns; **losses, VaR and ES are positive numbers**; an exception
  is `loss > VaR`; positive ES Z2 means ES is too low; forecasts at `t` use data up to `t-1`.
- No look-ahead. Any new rolling statistic needs a test that changing a future value does not
  change past outputs.
- Unit costs in USD per barrel, volumes in thousand barrels per day (kb/d).
- Illustrative parameters (network, basis volatility) must be labelled as assumptions in the UI
  and docs. Never present synthetic or assumed numbers as market facts.
- Secrets only via environment variables (`FRED_API_KEY`). Never log, cache or print them,
  never put them in URLs that appear in error messages.

## Testing rules

- Tests are offline and deterministic: fixed seeds, fixed end dates, `tmp_path`, stub providers.
  No test may call a real external API.
- Test the maths against hand-computed values, not against the code's own output.
- A bug fix starts with a failing test that reproduces it.
- Streamlit pages are covered by `tests/test_app_smoke.py` (stand-in) and
  `tests/test_app_streamlit.py` (real `AppTest`, skipped when Streamlit is missing).

## Anti-hallucination protocol

1. **Never invent** library functions, parameters, API endpoints, response fields or package
   versions. If you are not sure, look at the installed package source (`python -c "import x;
   print(x.__file__)"`), the docs, or run a tiny experiment, then say what you verified.
2. When a claim depends on an external service (FRED, PortWatch, World Bank), fetch a real
   response or say that it is unverified. Parsers must be written against a real payload.
3. State uncertainty explicitly: "verified by running X" vs "assumed from docs".
4. Prefer small, reversible steps. Show the diff of what changed and why.
5. If a request conflicts with this file or looks wrong (for example a wrong sign convention),
   say so before implementing.
6. Do not add dependencies without asking. Prefer the standard library, pandas, numpy, scipy.
7. Do not rewrite working modules for style. Change only what the task needs.
8. If tests fail, fix the cause. Never delete or weaken a test to make it pass.

## Git

- Small commits, imperative English messages (`Add Kupiec test for zero exceptions`).
- Never commit `.env`, `.cache/`, secrets or large binaries. `data/snapshots/` is committed on
  purpose; only snapshot sources whose licence allows redistribution.
- Do not force-push `main`.

## Known constraints

- Free hosting has an ephemeral disk and sleeps when idle; the snapshot layer exists for that.
- The owner's laptop is an Intel MacBook Pro (macOS 15). Wheels for new Python versions can
  lag on x86_64 macOS, so keep dependencies light and rely on CI (Linux) as the main test bed.
- `pyarrow` and `duckdb` are optional at runtime (csv.gz and pandas fallbacks exist).
