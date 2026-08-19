.PHONY: scraper scraper-dev test run migrate migrate-rev migrate-check \
	run-clustering sync-images clusterer

# All targets assume the repo root. One .venv lives here.

scraper:
	uv sync --package scraper

scraper-dev:
	uv sync --package scraper --group dev --group test

clusterer:
	uv sync --package clusterer

test:
	uv run --package scraper --directory scraper pytest

run:
	uv run --package scraper --directory scraper python3 -m app.main

migrate:
	uv run --package database alembic -c packages/database/alembic.ini upgrade head

migrate-rev:
	uv run --package database alembic -c packages/database/alembic.ini revision --autogenerate -m "$(m)"

migrate-check:
	uv run --package database alembic -c packages/database/alembic.ini check

run-clustering:
	uv run --package scraper --directory scraper python3 -m scripts.run_clustering_script

sync-images:
	uv run --package scraper --directory scraper python3 -m scripts.sync_images_script
