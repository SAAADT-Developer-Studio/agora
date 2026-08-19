FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

COPY pyproject.toml uv.lock ./
COPY packages/database packages/database
COPY clusterer/pyproject.toml clusterer/

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --package clusterer --locked --no-install-project --no-dev

COPY clusterer clusterer

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --package clusterer --locked --no-dev

ENV PATH="/app/.venv/bin:$PATH"
WORKDIR /app/clusterer

CMD ["python3", "-m", "clusterer"]
