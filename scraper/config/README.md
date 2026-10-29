# Ranking config

`scraper/config/ranking.yaml` is the source of truth for story ranking settings.
The observation job (`python -m scripts.rank_clusters`) reads this file on every
run, including the systemd timer. The resolved `{version, parameters}` object
is stored on `ranking_run.config`.

vidik-backoffice opens pull requests that edit **only** this file.

## File the backoffice should write

| | |
| --- | --- |
| Path in git | `scraper/config/ranking.yaml` |
| Path in the scraper image | `/app/scraper/config/ranking.yaml` |
| Format | UTF-8 YAML, one document |
| Object shape | `{version, parameters}` |

`version` is a non-empty string. Production today is `initial-ranking-v1`.
Change it when the numbers change so a run can be told apart from the previous
policy.

`parameters` is an object with these sections, and no others:

- `article_contribution`
- `syndication`
- `coverage`
- `publisher_authority`
- `freshness`
- `momentum`
- `newsworthiness`
- `cluster_confidence`
- `ranking` (includes nested `article_strength`)

Write every parameter. The committed file lists the full current policy.
Field types and bounds are in `ranking.schema.json`, generated from the
ranking config models. The job checks the same models when it loads the file.

A JSON file with the same object is also accepted when `--config` ends in
`.json`. That is the shape stored on `ranking_run.config` and the shape
backoffice presets export. Pull requests should still change the YAML file,
not add a second JSON copy.

## What the job does with the file

`agora-ranking.service` runs:

```text
python -m scripts.rank_clusters --days 14 --config /app/scraper/config/ranking.yaml
```

A manual run with no `--config` reads the same file from the scraper tree
(`scraper/config/ranking.yaml` next to the package). The scraper image copies
that tree (`COPY scraper scraper`) and the image build fails if the file is
missing or empty.

Unknown sections are rejected. Values that fail the config models are
rejected. `.yaml`, `.yml`, and `.json` are the only accepted suffixes.

If the file is missing, unreadable, or invalid, the job logs the reason and
exits non-zero. `agora-ranking.service` is a oneshot, so systemd marks that
run failed. The job does not score with the Python field defaults in that
case. A silent fallback would store scores under a version string while using
a different policy than the file that was deployed.

Inside a file that does load, an omitted section or key is filled from the
Python model and the full object is what gets stored. That fill-in is only
for a file that parsed. List every parameter in the PR so the diff is the
whole policy.

`freshness.category_half_lives_hours` is merged with the built-in category
map when the file is loaded. Editing a listed value changes that category.
Adding a key adds a category. Removing a built-in key puts that category's
Python half-life back. The committed file lists every built-in category, so
loading it does not change the map.

## What a merge does

Merging to `main` redeploys the Hetzner scraper (the deploy workflow builds
the image and Ansible updates the timer unit). The next ranking run uses the
new numbers.

Scores are observation-only. They are written to `story_rank` and
`ranking_run` with `source = story`. Feed order does not read those rows.
This file does not change the ranking formula, the database schema, or which
rows the job is allowed to delete.
