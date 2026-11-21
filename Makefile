.PHONY: sync lint format test check data data-offline build boundaries wards climate mart verify all clean api bench

sync:
	uv sync --all-groups

lint:
	uv run ruff check .

format:
	uv run ruff format .

test:
	uv run pytest

check: lint test

# One command: acquire every catalogued source, then build the mart.
# Stages reuse cached raw inputs, so a warm run does no network I/O.
data:
	uv run climate-resilience data

# Verify the cache only. No network, no build. Used when offline and in CI.
data-offline:
	uv run climate-resilience data --offline

# Rebuild derived outputs from already-acquired inputs.
build:
	uv run climate-resilience mart

boundaries:
	uv run climate-resilience boundaries

wards:
	uv run climate-resilience wards

climate:
	uv run climate-resilience climate

mart:
	uv run climate-resilience mart

api:
	uv run climate-resilience serve --port 8000

bench:
	uv run climate-resilience bench

verify:
	uv run climate-resilience verify
	uv run python scripts/independent_check.py
	uv run climate-resilience catalogue

all: data verify check

clean:
	rm -f data/mart.db
	rm -rf data/raw data/processed data/manifests
