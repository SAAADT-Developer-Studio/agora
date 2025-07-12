# News Scraper and Clusterer

- Fetches RSS feeds of multiple news providers
- Fetches their content
- Generates the embeddings for the articles
- Does DBSCAN clustering on the window of last X articles
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
uv run python3 -m app.main -providers=rtv,delo
```

### Docker

```bash
docker build -t vidik-scraper .
docker run --env-file ./.env vidik-scraper
```
