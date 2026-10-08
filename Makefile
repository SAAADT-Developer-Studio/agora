.PHONY: scraper scraper-dev test run migrate migrate-rev migrate-check \
	run-clustering rank-clusters export-ranking-sample export-articles sync-images clusterer clusterer-dev

# All targets assume the repo root. One .venv lives here.

scraper:
	uv sync --package scraper

scraper-dev:
	uv sync --package scraper --group dev --group test

clusterer:
	uv sync --package clusterer

clusterer-dev:
	uv sync --package clusterer --group test

test:
	uv run --package scraper --directory scraper pytest
	uv run --package clusterer --directory clusterer pytest

run:
	uv run --package scraper --directory scraper python3 -m app.main

migrate:
	uv run --package database alembic -c packages/database/alembic.ini upgrade head

migrate-rev:
	uv run --package database alembic -c packages/database/alembic.ini revision --autogenerate -m "$(m)"

migrate-check:
	uv run --package database alembic -c packages/database/alembic.ini check

run-clustering:
	uv run --package scraper --directory scraper python3 -m scripts.run_clustering_script $(ARGS)

rank-clusters:
	uv run --package scraper --directory scraper python3 -m scripts.rank_clusters $(ARGS)

export-ranking-sample: export-articles

export-articles: DAYS ?= 5
export-articles:
	uv run --package scraper --directory scraper python3 -m scripts.export_articles --days "$(DAYS)" $(if $(OUTPUT),--output "$(OUTPUT)") $(ARGS)

sync-images:
	uv run --package scraper --directory scraper python3 -m scripts.sync_images_script
