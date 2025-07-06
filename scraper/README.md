# News Scraper and Clusterer

- Fetches RSS feeds of multiple news providers
- Fetches their content
- Generates the embeddings for the articles
- Does DBSCAN clustering on the window of last X articles
- Generates Cluster Titles with an LLM

```bash
# run with
poetry run python3 -m app.main
```

```bash
# limit to certain providers
poetry run python3 -m app.main -providers=rtv,delo
```
