# AGENTS.md

uv workspace. Run every `uv` / `make` command from the **repo root**. The only venv is `.venv` here.

```
scraper/              live scrape + current clustering
clusterer/            new clustering (empty)
packages/database/    schema, repos, Alembic (single source of truth)
```

`uv sync` without `--package` installs the empty root project. Always pass `--package scraper` or `--package clusterer`.

`--directory scraper` is required for anything that imports `app` / `scripts`. Env vars live in the repo-root `.env`.

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
make sync-images
make replay-export start=2026-10-19T06:00 hours=32 name=oct19   # needs REPLAY_DATABASE_URL, read-only
make replay name=oct19 ARGS="--run try1"                         # LLM replies cached, capped at $1
```

Test clustering changes with the replay harness (`clusterer/replay.py`) before shipping them. It runs `pipeline.run_batch`, the same code as production, over frozen past articles and writes a report under `clusterer/.replay/`. Use `--no-llm` for free threshold sweeps, `--span-days N` to try another story lifespan.

Alembic lives in `packages/database/`. Never run `uv sync` inside `scraper/` or `clusterer/` — that creates a nested `.venv`.
