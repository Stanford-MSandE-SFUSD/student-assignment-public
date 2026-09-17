.PHONY: install test lint format docs clean-checkout

install:
	uv sync

test:
	uv run python -m pytest tests -q

lint:
	uv run ruff check .

format:
	uv run ruff format .
	uv run ruff check --fix .

docs:
	cd docs && uv run $(MAKE) html

clean-checkout:
	bash scripts/test_clean_checkout.sh
