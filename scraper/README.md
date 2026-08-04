# News Scraper and Clusterer

- Fetches RSS feeds of multiple news providers
- Fetches their content
- Generates the embeddings for the articles
- Does HDBSCAN clustering on the window of last X articles
- Generates Cluster Titles with an LLM

## Setup

Install [uv](https://docs.astral.sh/uv)

```bash
# install packages
uv sync
```

```bash
# run with
uv run python3 -m app.main
```

```bash
# limit to certain providers
uv run python3 -m app.main --providers=rtv,delo
```

## Testing

```bash
# Install test dependencies
uv sync --group test

# Run tests
make test
# or
uv run pytest

# Run tests with verbose output
make test-verbose
```

### Docker

```bash
docker build -t vidik-scraper .
docker run --env-file ./.env vidik-scraper
```

### Migrations

```bash
uv run alembic revision --autogenerate -m "added or removed something"
# check /scraper/alembic/versions/[migration].py if the migration is ok
uv run alembic upgrade head

# check if the migration was applied sucessfully
uv run alembic check
```

### Wikimedia cluster images

`cluster_v2.wiki_image_urls` is positionally paired with
`cluster_v2.wiki_image_metadata`. A consumer that displays an image must also use the matching
metadata record. For CC BY and CC BY-SA images, render the stored `attribution` and link to both
`source_url` (Wikimedia Commons) and `license_url`; use `attribution_url` when it is present. If the
image is cropped or otherwise changed, the UI must also say so. Do not display an
attribution-required image from `wiki_image_urls` alone.

### Adding a new provider

Instructions for adding a new provider are [here](./app/providers/README.md)
