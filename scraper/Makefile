.PHONY: test test-verbose install install-dev

install:
	uv sync

install-dev:
	uv sync --group dev --group test

test:
	uv run pytest

test-verbose:
	uv run pytest -v

transform-images:
	uv run python3 scripts/transform_images.py

# TODO: Add lint, format, type-check targets
# TODO: Add test-watch target for development
# TODO: Add clean target for cache cleanup