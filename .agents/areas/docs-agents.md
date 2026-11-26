# docs-agents

Paths: `docs/ARCHITECTURE.md`, `docs/API_VERSIONING.md`, `docs/FEATURE_FLAGS.md`, `docs/OPERATIONS.md`, `README.md`, `AGENTS.md`, `UPDATES.md`, `.agents/**`, `.codesight/**`, `.claude/**`, `plans/**`, `_bmad-output/**`, `review-artifacts/**`.

Purpose: documentation and agent tooling. `docs/MIGRATIONS.md` belongs to api-domain, `docs/WEBHOOKS.md` to api-events.

Entry points:
- `AGENTS.md`: project context, frontend rules, migration rules, dev ports.
- `docs/ARCHITECTURE.md`: topology and domain model.
- `.codesight/`: generated context map (`CODESIGHT.md`, `wiki/`, `routes.md`, `schema.md`, `graph.md`).
- `.agents/areas/`: this area map.

Conventions:
- `AGENTS.md` says `npx codesight --wiki` regenerates the `.codesight` wiki.
- `docs/OPERATIONS.md` covers request tracing, retention, backup and restore.
- `docs/FEATURE_FLAGS.md`: flags are stored in `workspaces.flags`; a missing key means enabled.

Pitfalls:
- `docs/ARCHITECTURE.md` describes the web app as Refine + Antd; `apps/web/package.json` has no `antd` and the code uses shadcn/ui.

Checks: none defined in the repo's docs or CI.
