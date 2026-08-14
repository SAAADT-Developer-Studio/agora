# News Scraper and Clusterer

- Fetches RSS feeds of multiple news providers
- Fetches their content
- Generates the embeddings for the articles
- Does HDBSCAN clustering on the window of last X articles
- Generates Cluster Titles with an LLM

Setup, tests, run, migrations, and scripts are documented in the [repo README](../README.md). Run them from the repo root (`make scraper`, `make test`, `make run`, `make migrate`, …).

### Wikimedia cluster images

`cluster_v2.wiki_image_urls` is positionally paired with
`cluster_v2.wiki_image_metadata`. A consumer that displays an image must also use the matching
metadata record. For CC BY and CC BY-SA images, render the stored `attribution` and link to both
`source_url` (Wikimedia Commons) and `license_url`; use `attribution_url` when it is present. If the
image is cropped or otherwise changed, the UI must also say so. Do not display an
attribution-required image from `wiki_image_urls` alone.

### Adding a new provider

Instructions for adding a new provider are [here](./app/providers/README.md)
