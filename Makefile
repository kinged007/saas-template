SHELL := /bin/bash
.DEFAULT_GOAL := help

SUDO := $(shell [ "$$(id -u)" -eq 0 ] 2>/dev/null && echo "" || echo sudo)

.PHONY: help setup dev api api-install api-migrate api-seed api-test api-lint web web-install web-build infra-up infra-down

help:
	@echo "SaaS Template targets (development runs from the terminal — no docker needed):"
	@echo "  make setup        one-time: install uv + Node.js if missing (fnm -> apt -> nvm)"
	@echo "  make dev          install deps, migrate, seed, then run api (:8000) + web (:5173)"
	@echo "  make api-install  install backend deps (uv sync)"
	@echo "  make api-migrate  run alembic migrations (starts embedded postgres)"
	@echo "  make api-seed     seed default demo users + workspaces"
	@echo "  make api          run backend (uvicorn, :8000)"
	@echo "  make api-test     run backend tests (sqlite in-memory)"
	@echo "  make web-install  install frontend deps"
	@echo "  make web          run frontend (vite, :5173)"
	@echo "  make web-build    type-check + build frontend"
	@echo ""
	@echo "Optional (prod-like testing with NATS, requires docker):"
	@echo "  make infra-up     start postgres + nats in docker"
	@echo "  make infra-down   stop docker infra"

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
	cd apps/api && uv run python src/seed.py

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

infra-up:
	docker compose -f infra/docker/docker-compose.dev.yml up -d

infra-down:
	docker compose -f infra/docker/docker-compose.dev.yml down
