#!/usr/bin/env bash
# Idempotent repository bootstrap for the Vidik (agora) monorepo.
# Installs toolchains and Python dependencies for the `scraper` and `api` services.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# --- System packages (guarded; normally already present in the base snapshot) ---
if ! command -v psql >/dev/null 2>&1 || ! dpkg -s build-essential >/dev/null 2>&1; then
  sudo apt-get update
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    build-essential postgresql postgresql-contrib curl git ca-certificates
fi

# --- uv (Python package/toolchain manager) ---
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
export PATH="$HOME/.local/bin:$PATH"
# Expose uv on the system PATH so `start` and terminals find it without shell hacks.
sudo ln -sf "$HOME/.local/bin/uv" /usr/local/bin/uv
sudo ln -sf "$HOME/.local/bin/uvx" /usr/local/bin/uvx

# --- Local development environment files (real secrets injected as env vars win) ---
# `dotenv` does not override existing environment variables, so providing real
# OPENAI_API_KEY / DATABASE_URL / etc. as Cloud Agent secrets overrides these defaults.
if [ ! -f scraper/.env ]; then
  cat > scraper/.env <<'EOF'
APP_ENV=development
DATABASE_URL=postgresql://vidik:vidik@localhost:5432/vidik
OPENAI_API_KEY=dev-placeholder-not-used-offline
OPENROUTER_API_KEY=dev-placeholder-not-used-offline
PEXELS_API_KEY=dev-placeholder-not-used-offline
EOF
fi
if [ ! -f api/.env ]; then
  cat > api/.env <<'EOF'
DATABASE_URL=postgresql://vidik:vidik@localhost:5432/vidik
HOST=0.0.0.0
PORT=8000
ENVIRONMENT=development
DEBUG=true
APP_ENV=development
EOF
fi

# --- Python dependencies (uv manages the required Python 3.13 automatically) ---
(cd scraper && uv sync --group dev --group test)
(cd api && uv sync)

echo "install.sh: complete"
