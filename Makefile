SHELL := /bin/bash
.DEFAULT_GOAL := help

SUDO := $(shell [ "$$(id -u)" -eq 0 ] 2>/dev/null && echo "" || echo sudo)

.PHONY: help setup dev api api-install api-migrate api-seed api-test api-lint web web-install web-build web-typecheck hooks-install infra-up infra-down nats-up nats-down nats-status nats-logs

# USE_SQLITE=1 (env or `make <target> USE_SQLITE=1`): use the per-checkout
# sqlite dev DB (apps/api/dev.db) instead of embedded postgres. Exported so it
# reaches sub-makes and dev.py's child processes. (A trailing `--sqlite` flag
# is not possible: GNU make parses `--long` args as its own options.)
ifdef USE_SQLITE
export USE_SQLITE
endif

help:
	@echo "SaaS Template targets (development runs from the terminal — no docker needed):"
	@echo "  make setup        one-time: install uv + Node.js if missing (fnm -> apt -> nvm)"
	@echo "  make dev          install deps, migrate, seed, then run api (:8000) + web (:5173)"
	@echo "  make api-install  install backend deps (uv sync)"
	@echo "  make api-migrate  run alembic migrations (starts embedded postgres)"
	@echo "  USE_SQLITE=1 make dev  sqlite dev DB (apps/api/dev.db) instead of postgres"
	@echo "  make api-seed     seed default demo users + workspaces"
	@echo "  make api          run backend (uvicorn, :8000)"
	@echo "  make api-test     run backend tests (sqlite in-memory)"
	@echo "  make api-lint     ruff check + format check (same as pre-commit hook)"
	@echo "  make hooks-install install pre-commit hooks (uv tool install pre-commit first)"
	@echo "  make web-install  install frontend deps"
	@echo "  make web          run frontend (vite, :5173)"
	@echo "  make web-build    type-check + build frontend"
	@echo ""
	@echo "Optional (prod-like testing with NATS, requires docker — no compose needed):"
	@echo "  make nats-up      start a NATS JetStream container (plain docker run)"
	@echo "  make nats-down    stop + remove the NATS container"
	@echo "  make nats-status  show NATS container + JetStream state"
	@echo "  make nats-logs    tail NATS container logs"
	@echo "  make api-test-nats run backend tests against a real NATS (skips if nats not up)"

setup:
	@if command -v uv >/dev/null 2>&1; then \
		echo "==> uv already installed: $$(uv --version)"; \
	else \
		echo "==> Installing uv..."; \
		curl -LsSf https://astral.sh/uv/install.sh | sh || { echo "error: uv install failed (need curl + internet)"; exit 1; }; \
	fi
	@if command -v node >/dev/null 2>&1; then \
		echo "==> Node.js already installed: $$(node --version)"; \
		NODE_MAJOR=$$(node --version | cut -d. -f1 | tr -d v); \
		if [ "$$NODE_MAJOR" -lt 18 ]; then \
			echo "    warning: Vite 5 needs Node >= 18"; \
		fi; \
	else \
		echo "==> Node.js not found — trying installers (fnm, then apt, then nvm)..."; \
		FNM_BIN=""; \
		if command -v fnm >/dev/null 2>&1; then \
			echo "    -> fnm already installed"; \
		elif curl -fsSL https://fnm.vercel.app/install | bash >/dev/null 2>&1; then \
			echo "    -> installed via fnm"; \
		else \
			echo "    fnm install failed"; \
		fi; \
		for d in "$$HOME/.fnm" "$$XDG_DATA_HOME/fnm" "$$HOME/.local/share/fnm"; do \
			if [ -n "$$d" ] && [ -x "$$d/fnm" ]; then FNM_BIN="$$d"; break; fi; \
		done; \
		if [ -n "$$FNM_BIN" ]; then \
			export PATH="$$FNM_BIN:$$PATH"; \
			fnm install --lts; \
		elif command -v apt-get >/dev/null 2>&1; then \
			echo "    -> trying apt-get"; \
			$(SUDO) apt-get update && $(SUDO) apt-get install -y nodejs npm || echo "    apt install failed"; \
		else \
			echo "    -> trying nvm"; \
			curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash >/dev/null 2>&1 || { echo "error: all installers failed — install Node.js from https://nodejs.org"; exit 1; }; \
			export NVM_DIR="$$HOME/.nvm"; \
			. "$$NVM_DIR/nvm.sh"; \
			nvm install --lts; \
		fi; \
		if command -v node >/dev/null 2>&1; then \
			echo "==> Node.js ready: $$(node --version)"; \
		else \
			echo "==> Done — open a new terminal (or run: source ~/.bashrc) so node is on PATH"; \
		fi; \
	fi

dev:
	@command -v uv >/dev/null 2>&1 || { echo "error: uv not found — run 'make setup' first"; exit 1; }
	@command -v node >/dev/null 2>&1 || { echo "error: node not found — run 'make setup' first"; exit 1; }
	$(MAKE) api-install web-install
	$(MAKE) api-migrate
	$(MAKE) api-seed
	@echo "==> Starting API (:8000) and web (:5173) — Ctrl-C stops both"
	@if command -v python3 >/dev/null 2>&1; then \
		python3 scripts/dev.py; \
	elif [ -x apps/api/.venv/bin/python ]; then \
		apps/api/.venv/bin/python scripts/dev.py; \
	else \
		echo "error: python3 not found — install Python 3 (the API requires it anyway)"; exit 1; \
	fi

api-install:
	cd apps/api && uv sync --extra dev

api-migrate:
	cd apps/api && uv run alembic upgrade head

api-seed:
	cd apps/api && uv run python -m src.seed

api:
	cd apps/api && uv run uvicorn src.main:app --reload --port 8000

api-test:
	cd apps/api && uv run pytest

api-lint:
	cd apps/api && uv run ruff check . && uv run ruff format --check .

web-install:
	cd apps/web && npm install

web:
	cd apps/web && npm run dev

web-build:
	cd apps/web && npm run build

web-typecheck:
	cd apps/web && npx tsc -p tsconfig.json --noEmit

hooks-install:
	pre-commit install --config .pre-commit-config.yaml

infra-up:
	./scripts/nats.sh start

infra-down:
	./scripts/nats.sh stop

nats-up:
	./scripts/nats.sh start

nats-down:
	./scripts/nats.sh stop

nats-status:
	./scripts/nats.sh status

nats-logs:
	./scripts/nats.sh logs

api-test-nats:
	./scripts/nats.sh start
	cd apps/api && uv run pytest tests/test_nats_integration.py -v
