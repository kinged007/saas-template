# infra-ci

Paths: `infra/docker/**`, `infra/helm/saas-template/**`, `infra/terraform/aws/**`, `.github/workflows/**`, `Makefile`, `scripts/dev.py`, `scripts/nats.sh`, `.pre-commit-config.yaml`, root `package.json` and `package-lock.json`.

Purpose: local development commands, CI, container images, Kubernetes chart, AWS Terraform.

Entry points:
- `Makefile`: `make help` lists targets (`setup`, `dev`, `api-test`, `web-test`, `db-check`, `nats-up`, ...).
- `scripts/dev.py`: supervisor for `make dev`; starts API and web and stops both on exit, signal or crash.
- `scripts/nats.sh`: NATS JetStream container via plain `docker run`.
- `.github/workflows/ci.yml`: jobs `api-lint`, `api-test`, `db-check`, `web-build`, `web-test`.
- `.github/workflows/e2e.yml`: job `web-e2e`, main only.
- `infra/docker/`: `Dockerfile.api`, `Dockerfile.web`, `nginx.conf`, dev and prod compose files.

Conventions:
- Development runs from the terminal without docker; docker is only for NATS.
- `make dev` ports: `API_PORT` (8000), `WEB_PORT` (5173).
- The Node floor in `Makefile` (`WEB_NODE_MAJOR`, `WEB_NODE_MINOR`) matches `engines` in `apps/web/package.json`; `apps/api/tests/test_node_floor.py` checks `make check-node`.
- Python is pinned to 3.12 in CI uv jobs.

Pitfalls:
- A process started by `dev.py` must be stopped by it; do not leave orphans on :8000 or :5173.
- Do not add a CI job that duplicates one in `ci.yml`.

Checks: `make db-check`, `make api-lint`; pre-commit runs ruff and `tsc --noEmit`.
