# AGENTS.md

uv workspace. Run every `uv` / `make` command from the **repo root**. The only venv is `.venv` here.

```
scraper/              live scrape + current clustering
clusterer/            new clustering (empty)
packages/database/    schema, repos, Alembic (single source of truth)
```

`uv sync` without `--package` installs the empty root project. Always pass `--package scraper` or `--package clusterer`.

`--directory scraper` is required for anything that imports `app` / `scripts` or loads `scraper/.env`.

## Commands

```bash
make scraper          # uv sync --package scraper
make scraper-dev      # + dev/test groups
make clusterer
make test
make run
make migrate
make migrate-rev m="what changed"
make migrate-check
make run-clustering
make sync-images
```

Alembic lives in `packages/database/`. Never run `uv sync` inside `scraper/` or `clusterer/` — that creates a nested `.venv`.
