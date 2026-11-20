.PHONY: sync lint format test check boundaries wards climate mart verify clean

sync:
	uv sync --all-groups

lint:
	uv run ruff check .

format:
	uv run ruff format .

test:
	uv run pytest

check: lint test

boundaries:
	uv run climate-resilience boundaries

wards:
	uv run climate-resilience wards

climate:
	uv run climate-resilience climate

mart:
	uv run climate-resilience mart

verify:
	uv run python scripts/independent_check.py
	uv run climate-resilience catalogue

clean:
	rm -f data/mart.db
	rm -rf data/raw data/processed data/manifests
