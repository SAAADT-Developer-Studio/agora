FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

RUN apt-get update && apt-get install -y build-essential

COPY pyproject.toml uv.lock ./
COPY packages/database packages/database
COPY scraper/pyproject.toml scraper/

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --package scraper --locked --no-install-project --no-dev

COPY scraper scraper
RUN touch scraper/README.md

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --package scraper --locked --no-dev

ENV PATH="/app/.venv/bin:$PATH"
WORKDIR /app/scraper

CMD ["python3", "-m", "app.main"]
