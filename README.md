# Vidik

uv workspace. Run commands from the **repo root**. The only venv is `.venv` here.

```
scraper/              news scrape + current clustering
clusterer/            new clustering (empty)
packages/database/    schema, repos, Alembic
```

Install [uv](https://docs.astral.sh/uv), then:

```bash
make scraper          # install scraper + database
make scraper-dev      # + test/dev deps
make test
make run              # scraper loop (needs scraper/.env)
```

```bash
make migrate                              # alembic upgrade head
make migrate-rev m="what changed"         # autogenerate; check the file before applying
make migrate-check
```

Scraper-only scripts (still the old clusterer, live in `scraper/`):

```bash
make run-clustering
make sync-images
```

Docker (repo root):

```bash
docker build -f scraper/Dockerfile -t vidik-scraper .
docker build -f clusterer/Dockerfile -t vidik-clusterer .
docker compose up -d
```

Scraper domain notes (providers, Wikimedia): [scraper/README.md](scraper/README.md).

Similar site with article clustering by news event: https://www.times.si/

## Ideas:

- show article alterations
- people mentioned in article (like youtube)
- visualize the frequency of publishing for a news provider with a graph

## Terraform

```bash
cd infra
terraform init
terraform apply -var-file=prod.tvars
```

## SSH

```bash
ssh root@<server_ip>
```
