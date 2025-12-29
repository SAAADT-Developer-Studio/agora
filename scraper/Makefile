.PHONY: test test-verbose install install-dev

install:
	uv sync

install-dev:
	uv sync --group dev --group test

test:
	uv run pytest

test-verbose:
	uv run pytest -v

sync-images:
	uv run python3 -m scripts.sync_images_script

bootstrap-cluster-run:
	uv run python3 -m scripts.bootstrap_cluster_run_script

migrate-clusters:
	uv run python3 -m scripts.migrate_clusters_script

run-clustering:
	uv run python3 -m scripts.run_clustering_script

# TODO: Add lint, format, type-check targets
# TODO: Add test-watch target for development
# TODO: Add clean target for cache cleanup