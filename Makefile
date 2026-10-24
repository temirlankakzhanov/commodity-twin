.DEFAULT_GOAL := help
# Use the project virtualenv when it exists, otherwise the interpreter on PATH.
PY ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
VENV_PY ?= python3.12
export PYTHONPATH := .

.PHONY: help install hooks run test cov lint format check fetch snapshot figures docker clean

help:  ## Show this help
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-10s %s\n", $$1, $$2}'

install:  ## Create .venv and install dev dependencies (wheels only: never compiles from source)
	$(VENV_PY) -m venv .venv
	.venv/bin/pip install --upgrade pip
	.venv/bin/pip install --only-binary=:all: -r requirements-dev.txt
	@$(MAKE) --no-print-directory hooks

hooks:  ## Install git pre-commit hooks (needs a git repository: run git init first)
	@if [ -d .git ]; then .venv/bin/pre-commit install; \
	else echo "No .git directory yet: run 'git init' and then 'make hooks'."; fi

run:  ## Start the Streamlit app
	$(PY) -m streamlit run streamlit_app.py

test:  ## Run the test suite
	$(PY) -m pytest

cov:  ## Tests with coverage report
	$(PY) -m pytest --cov=mtwin --cov-report=term-missing

lint:  ## Lint and check formatting
	$(PY) -m ruff check .
	$(PY) -m ruff format --check .

format:  ## Auto-fix lint issues and format
	$(PY) -m ruff check --fix .
	$(PY) -m ruff format .

check: lint test  ## Everything CI runs

fetch:  ## Download all datasets into the local cache
	$(PY) scripts/fetch_data.py

snapshot:  ## Download and write committed snapshots (data/snapshots)
	$(PY) scripts/fetch_data.py --force --snapshot

figures:  ## Regenerate README figures from synthetic data
	$(PY) scripts/make_readme_figures.py

docker:  ## Build and run the container on http://localhost:8501
	docker build -t commodity-twin .
	docker run --rm -p 8501:8501 commodity-twin

clean:  ## Remove caches
	rm -rf .cache .pytest_cache .ruff_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
