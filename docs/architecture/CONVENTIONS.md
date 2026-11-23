# Architecture and coding conventions

> **Status:** normative · **Revision:** 2026-11-23 · measured against `main` @ `9c58d51e`
> **Explained in:** [ARCHITECTURE.md](../ARCHITECTURE.md) · [API_VERSIONING.md](../API_VERSIONING.md) ·
> [MIGRATIONS.md](../MIGRATIONS.md) · [FEATURE_FLAGS.md](../FEATURE_FLAGS.md) ·
> [DECISIONS.md](../product/DECISIONS.md)

This file states rules. ARCHITECTURE.md and the other documents above explain the design; when
they disagree with this file on a rule, this file applies. Every rule describes what the code
already does and cites the file it is read from. Where the code is not consistent, the rule is
the majority pattern and the exceptions are in [Known deviations](#known-deviations).

Rule IDs are `CONV-<AREA>-NN`. IDs are never reused. A removed rule keeps its number.

## How to use this file

- **Build agent:** the plan comment lists the `CONV-*` IDs the change touches, or `none`
  (`.agents/work-on-issues.md` §4). The PR does not add a Known deviation.
- **Reviewer:** gives pass, fail or n.a. for each relevant ID and runs the rule's **Check**
  itself; the plan's list is not evidence (`.agents/review_pr.md` §4). A fail is a major
  finding.
- **Deviation:** a change that breaks a rule needs an entry in
  [DECISIONS.md](../product/DECISIONS.md) that names the rule ID and the reason. Without the
  entry the change is not mergeable. Changing DECISIONS.md needs the maintainer
  ([ADMISSION.md §5](../product/ADMISSION.md#5-what-needs-the-maintainer)).
- **Check:** every command runs from the repo root. `returns nothing` means exit status 1 and
  no output.
- **Expected values:** a Check that prints a count or a file list states the value on `main`. A
  compliant change that moves the number or the list updates the expected value in the same PR;
  the reviewer judges whether the difference is the effect of the diff, not the number itself.

---

## EVT — events

Source: ARCHITECTURE.md §6, `apps/api/src/events/`, `apps/api/src/workflows/__init__.py`.

- **CONV-EVT-01** A side effect that belongs to another module (notification, audit entry,
  webhook delivery, email, job run) is requested by publishing an event. The producing
  service does not call the consuming module.
  Why: producers stay independent of consumers, and the NATS driver can deliver the event to
  any replica.
  Check: read: a service that creates a notification, audit entry, email or job run for another
  module does it through `publish_event`, `publish_audit` or `EventBus.publish`
  (`apps/api/src/events/publisher.py`).
- **CONV-EVT-02** The subject is a `Subjects.*` constant from `apps/api/src/events/subjects.py`,
  never a string literal. A new subject is added to `Subjects` and to `ALL`.
  Why: one list of subjects; a typo cannot create a subject nobody consumes.
  Check: `grep -rPzl "\.publish\(\s*[bBfFrRuU]*['\"]|publish_event\(\s*[\w.]+,\s*[bBfFrRuU]*['\"]" apps/api/src --include=*.py` returns nothing;
  `grep -rnE "Subjects\.[A-Z_0-9]+ *\+" apps/api/src` prints only
  `apps/api/src/services/conversations.py` (CONV-EVT-02 in Known deviations).
- **CONV-EVT-03** Every durable subject has exactly one workflow registered with
  `registry.register(Subjects.X, handler)` in `build_workflows`
  (`apps/api/src/workflows/__init__.py`). The set is asserted in
  `apps/api/tests/test_events.py::test_workflow_registry_wiring`; a new registration updates it.
  Why: a durable subject with no consumer accumulates in the JetStream stream.
  Check: `cd apps/api && uv run --extra dev pytest tests/test_events.py::test_workflow_registry_wiring -q` passes.
  The test asserts the registered set equals a fixed list; it does not compare against
  `Subjects.ALL`, so a durable subject added to `ALL` with no registration still passes (third
  row of CI check candidates).
- **CONV-EVT-04** A transient subject (realtime fan-out, nothing persisted) is listed in
  `TRANSIENT_SUBJECTS`, is published with `transient=True`, and its workflow is registered with
  `fanout=True`. A durable subject is none of these.
  Why: the NATS driver sends transient subjects over core NATS and rejects a durable consumer
  on them (`apps/api/src/events/nats.py`).
  Check: `grep -c "fanout=True" apps/api/src/workflows/__init__.py` prints `3`;
  `grep -rn "transient=True" apps/api/src | grep -v "apps/api/src/events/"` prints 5 lines, each
  publishing a subject in `TRANSIENT_SUBJECTS` (`NOTIFICATIONS_CREATED`,
  `CONVERSATION_MESSAGE_LIVE`, `CONVERSATION_RENAMED`).
- **CONV-EVT-05** `nats` is imported only inside `apps/api/src/events/`. Everything else depends
  on the `EventBus` interface (`apps/api/src/events/bus.py`).
  Why: the driver is selected by `EVENT_BUS_DRIVER` (CONV-CFG-01); code that imports `nats`
  breaks the in-process driver.
  Check: `grep -rnE "^\s*(import nats|from nats)" apps/api/src | grep -v "^apps/api/src/events/"` returns nothing.
- **CONV-EVT-06** Event consumers are workflow handlers wired through `WorkflowRegistry`
  (`apps/api/src/events/factory.py`). Nothing outside `apps/api/src/events/` calls
  `.subscribe(`.
  Why: the registry subscribes before the bus starts and owns the lifecycle.
  Check: `grep -rn "\.subscribe(" apps/api/src | grep -v "^apps/api/src/events/"` returns nothing.
- **CONV-EVT-07** A workflow handler opens its own DB session per event (`SessionFactory`) and
  tolerates redelivery: the bus is at-least-once. A row derived from an event stores the
  event's id (`SOURCE_EVENT_KEY` in `apps/api/src/events/bus.py`, `source_event_id` in
  `audit_payload`) so a redelivered event is not filed twice.
  Why: handlers may run in another process, and JetStream redelivers after a failure.
  Check: `cd apps/api && uv run --extra dev pytest tests/test_audit_workflow.py -q` passes;
  read: a new handler that writes rows has a redelivery test.
- **CONV-EVT-08** Events produced by one action share one `correlation_id` (created once, for
  example `apps/api/src/services/jobs.py` and `apps/api/src/services/workspaces.py`). A handler
  that publishes in response to an event passes `metadata.correlation_id`. The bus generates
  one when none is passed (`EventMetadata`).
  Why: delivery is unordered, and the id is the only link between the events of one action.
  Check: read: every `publish_event` / `publish_audit` / `bus.publish` call in the change that
  has a correlation id in scope passes it.

## API — HTTP contract

Source: ARCHITECTURE.md §8, `docs/API_VERSIONING.md`, `apps/api/src/api/`.

- **CONV-API-01** Every router is mounted under `/api/v1` with `prefix=API` in
  `apps/api/src/main.py`. A breaking change uses a new version prefix per
  `docs/API_VERSIONING.md`; within `v1` only additive changes are made.
  Why: clients send the prefix; the server stamps `X-API-Version`.
  Check: `grep -c "include_router" apps/api/src/main.py` and
  `grep -c "include_router(.*prefix=API)" apps/api/src/main.py` print the same number.
- **CONV-API-02** A list route follows `@refinedev/simple-rest`: it returns a JSON array and
  sets the `X-Total-Count` header. It parses the query with `parse_query` and applies it with
  `apply_query` from `apps/api/src/api/crud.py`, passing `sortable` and `filterable`
  whitelists. A new response header is added to `expose_headers` in `apps/api/src/main.py`.
  Why: Refine uses the dataProvider unchanged; client input never names a column.
  Check: `grep -L "apply_query" $(grep -l "X-Total-Count" apps/api/src/api/routes/*.py)` prints
  only the file listed under CONV-API-02 in Known deviations; `grep -c "X-Total-Count" apps/api/src/main.py` prints `1`.
- **CONV-API-03** Status codes: a `POST` that creates a resource returns 201 and the entity;
  `PATCH` returns 200 and the entity; `DELETE` returns 204 with no body; a `POST` that
  triggers an action on an existing resource returns the status named in its route decorator
  (200 by default; 202 or 204 where documented in the route).
  Why: simple-rest expects these codes.
  Check: `grep -rn "@router.delete" apps/api/src/api/routes | grep -v "status_code=204"` returns nothing;
  `grep -rn "@router.post" apps/api/src/api/routes | grep -v "status_code="` prints only action
  routes (suspend, reactivate, transfer, accept, decline, redeliver, token and credential
  routes under `auth.py` / `oauth.py`); read: a new create route has `status_code=201`.
- **CONV-API-04** Errors are `HTTPException(status, detail)`, which FastAPI renders as
  `{"detail": ...}`. Routes do not build `JSONResponse` for errors. Services raise domain
  exceptions (`WorkspaceNotFound`, `WorkspaceConflict`, ...) and the route maps them to a
  status. An invalid list query is 422.
  Why: the web dataProvider reads `detail` as the error message.
  Check: `grep -rln "JSONResponse" apps/api/src/api/routes` returns nothing;
  `grep -ln "HTTPException" apps/api/src/services/*.py` prints only the files listed under
  CONV-API-04 in Known deviations.
- **CONV-API-05** A path or query id that is not a valid UUID is 422 on a route whose param is
  typed `uuid.UUID` (FastAPI validates it); it is 404 `{"detail": "not found"}` on a route that
  looks the id up as a string (`apps/api/src/api/errors.py`). A well-formed id that names
  nothing is 404 on every route. A malformed id is never a 500. Source: GitHub issue #1806.
  Why: 422 says the client request is malformed; 404 says the resource is missing.
  Check: `cd apps/api && uv run --extra dev pytest tests/test_uuid_ids.py -q` passes; a new
  `uuid.UUID`-typed path param is added to `FRAMEWORK_VALIDATED_UUID_ROUTES` in that test.
- **CONV-API-06** A datetime in a response is serialized with `iso_or_none` or `ensure_utc`
  (`apps/api/src/core/dates.py`), so it carries a UTC offset.
  Why: SQLite returns naive values that browsers read as local time
  (`docs/API_VERSIONING.md`, "Recorded corrections").
  Check: `grep -rn "isoformat()" apps/api/src/api` returns nothing.
- **CONV-API-07** A correction to a status code or serialization of an existing route is
  recorded under "Recorded corrections" in `docs/API_VERSIONING.md` in the same PR.
  Why: it is not a version change, so the record is the only notice to clients.
  Check: read: a diff that changes a route's status code or value format also edits `docs/API_VERSIONING.md`.

## AUTH — authorization

Source: ARCHITECTURE.md §4 and §9, `apps/api/src/api/deps.py`, `apps/api/src/core/permissions.py`,
`apps/web/src/App.tsx`, `apps/web/src/providers/accessControlProvider.ts`.

- **CONV-AUTH-01** A workspace-scoped route (one that reads `X-Workspace-ID` through
  `get_current_workspace_id`) declares `Depends(require_permission(<CONSTANT>))`, with the
  constant from `apps/api/src/core/permissions.py`. Permission strings are not written inline.
  Why: the server is the only authority; the permission catalog is one list.
  Check: `grep -rnE "require_permission\(['\"]" apps/api/src` returns nothing;
  `grep -L "require_permission\|require_key_permission" apps/api/src/api/routes/*.py` prints
  `__init__.py`, `admin.py`, `auth.py`, `meta.py`, `oauth.py`, `profiles.py`, `ws.py`, and each
  of those has its own guard (CONV-AUTH-02, `require_target_profile_update`, token handshake,
  public) - a new route file is not added to this list. That grep only finds a file with no
  guard at all, so it does not see an unguarded route added to a router that already has one;
  read: every route the diff adds or changes that depends on `get_current_workspace_id`
  declares `Depends(require_permission(<CONSTANT>))` or `Depends(require_key_permission(...))`.
  The pytest check in CI check candidates tests this per route.
- **CONV-AUTH-02** Deployment-wide routes (`/admin/*`, `/jobs/global/*`, workspace ownership
  transfer) depend on `require_superuser` or call `require_deployment_admin`. These do not
  replace the workspace check on workspace-scoped routes.
  Why: the bootstrap superuser does not bypass workspace permissions (ARCHITECTURE.md §4).
  Check: `grep -c "@router\." apps/api/src/api/routes/admin.py` and
  `grep -c "Depends(require_superuser)" apps/api/src/api/routes/admin.py` print the same number;
  read: each route in `admin.py` depends on `require_superuser`, and a `/jobs/global/*` route or
  a workspace ownership transfer outside `admin.py` calls `require_deployment_admin` itself.
  Counting `require_superuser` mentions does not test the rule: it also matches the import and
  two docstring lines.
- **CONV-AUTH-03** API-key requests are authorized against the key's own permission list, never
  the owner's role. That logic lives in `require_permission` and `require_key_permission`
  (`apps/api/src/api/deps.py`) only.
  Why: a leaked key is limited to the permissions it was minted with.
  Check: `grep -rn "api_key.permissions" apps/api/src | grep -v "^apps/api/src/api/deps.py"` prints four lines: two in `jobs.py` (listed under CONV-AUTH-03 in Known deviations) and two that only report the key's grant (`workspaces.py`, `auth.py`).
- **CONV-AUTH-04** Every authenticated page is a route inside the `/` layout wrapped in
  `<Authenticated fallback={<ToLogin />}>` in `apps/web/src/App.tsx`. Routes outside it are the
  public set: `/login`, `/register`, `/forgot-password`, `/reset-password`,
  `/invitations/accept`, `/oauth/callback`, `/verify-email`. A route that reads the active
  workspace sits inside `<RequireWorkspace />`.
  Why: one guard for sign-in; the workspace-free routes stay reachable with no workspace.
  Check: `grep -c "<Authenticated" apps/web/src/App.tsx` prints `3` (the `/` layout, `/login`,
  `/register`); read: a new route outside the `/` layout is in the public set above.
- **CONV-AUTH-05** UI is gated with `useCan`, `<CanAccess>` or the ACL-aware `CreateButton`.
  `accessControlProvider` maps (resource, action) to a backend permission string in
  `PERMISSION_MAP` (`apps/web/src/providers/accessControlProvider.ts`). A new resource that
  needs a permission gets a `PERMISSION_MAP` entry. The backend is the final authority.
  Why: the UI hides what the server would refuse; the server still refuses.
  Check: `grep -rn "PERMISSION_MAP" apps/web/src | grep -v "accessControlProvider.ts"` returns
  nothing. Four `resources` entries have no key: `notifications` (those routes are gated by the
  key-only scopes in `KEY_ONLY_PERMISSIONS`, which no role holds) and `admin-users`,
  `admin-workspaces`, `admin-audit` (`AdminLayout` blocks every non-superuser). A new resource is
  not added to this list unless it is one of those two kinds; read: each new `resources` entry in
  `App.tsx` that maps to a permission has a `PERMISSION_MAP` key.
- **CONV-AUTH-06** A page does not read or write tokens or sessions. A page that needs session
  state gets it from `useGetIdentity` or `useIsAuthenticated`, not from `tokenStore`.
  The files that call `tokenStore` are the providers that own the session
  (`providers/authProvider.ts`, `providers/dataProvider.ts`, `providers/liveProvider.ts`), the
  workspace context (`contexts/WorkspaceContext.tsx`), `hooks/useProfile.ts`, the store itself
  (`utils/storage.ts`), and the two screens that establish a session
  (`pages/LoginPage.tsx`, `components/AuthConfig.tsx`).
  Why: one place changes when the session model changes (ARCHITECTURE.md §5).
  Check: `grep -rln "tokenStore" apps/web/src --include=*.ts --include=*.tsx | grep -v "\.test\."`
  prints those eight files and nothing else; read: a new page obtains identity through a hook.

## DATA — models, services, migrations

Source: `apps/api/src/models/`, `apps/api/src/services/`, `docs/MIGRATIONS.md`,
[DECISIONS.md D-04](../product/DECISIONS.md), `AGENTS.md` (High-impact files).

- **CONV-DATA-01** Id and id-shaped foreign-key columns use `StringUUID` from
  `apps/api/src/db/base.py`, with `default=lambda: str(uuid.uuid4())` for primary keys. Models
  inherit `Base` and are imported in `apps/api/src/models/__init__.py`.
  Why: one type works on SQLite and PostgreSQL, and `errors.py` classifies bad ids by it.
  Check: `grep -rnE "postgresql import|\bUuid\b|\bUUID\(" apps/api/src/models` returns nothing.
- **CONV-DATA-02** Models are the source of truth for the schema. A model change ships with a
  migration generated by `make db-new` (template) or `make db-new-project` (adopter), reviewed
  and committed.
  Why: `docs/MIGRATIONS.md`.
  Check: `make db-check` prints `PASS: migration chain is clean`.
- **CONV-DATA-03** A new migration's revision id is a 14-digit UTC timestamp and its file is
  `<timestamp>_<slug>.py` (D-04). `0001`-`0020` are the only numbered files. Project migrations
  are in `apps/api/alembic/project_versions/`, template migrations in
  `apps/api/alembic/versions/`.
  Why: independently authored timestamps do not collide.
  Check: `find apps/api/alembic/versions apps/api/alembic/project_versions -name '*.py' -printf '%f\n' | grep -vE '^(00(0[1-9]|1[0-9]|20)_|[0-9]{14}_)'` returns nothing.
- **CONV-DATA-04** Timestamps are UTC-aware: columns come from `TimestampMixin`
  (`apps/api/src/db/base.py`); code takes the time from `now_utc()`
  (`apps/api/src/core/dates.py`), not `datetime.utcnow()` or `datetime.now()`.
  Why: naive values are read as local time (CONV-API-06).
  Check: `grep -rnE "utcnow\(|datetime\.now\(\)" apps/api/src` returns nothing.
- **CONV-DATA-05** Database access and business rules are in `apps/api/src/services/`. A
  service commits its own unit of work and raises domain exceptions; a route does not call
  `commit()`.
  Why: a service can be called from a route, a workflow or a job with the same result.
  Check: `grep -rn "commit()" apps/api/src/api/routes` prints only the lines listed under
  CONV-DATA-05 in Known deviations.
- **CONV-DATA-06** Application settings are read through `settings` in
  `apps/api/src/settings.py`, not `os.environ`.
  Why: one place defines names, types and defaults.
  Check: `grep -rnE "os\.environ|os\.getenv" apps/api/src` prints only `apps/api/src/db/embedded.py`.
- **CONV-DATA-07** A change to a file listed under "High-impact files" in `AGENTS.md` names the
  importers it checked in the plan. A change to a model, `apps/api/src/db/session.py` or
  `apps/api/src/settings.py` states the effect on adopters' migrations and `.env`.
  Why: these files are imported by 9-17 others.
  Check: read: the plan names the importers (`grep -rn "<module>" apps/api/src apps/web/src`).

## FE — web (Refine)

Source: `apps/web/src/App.tsx`, `apps/web/src/pages/`, `apps/web/src/components/refine-ui/`.
These rules apply to all new pages. A touched page that is listed under FE in Known deviations is
not required to be migrated; touching it is a chance to fix it, on the same terms as every other
Known deviation.

- **CONV-FE-01** Register `create` on every resource that has a create flow, in
  `apps/web/src/App.tsx` (`{ name: "x", list: "/x", create: "/x/create" }`). Create is a page,
  never a dialog on the list page.
  Why: Refine links the `CreateButton` to the create route; a dialog cannot be linked.
  Check: `grep -n "create:" apps/web/src/App.tsx` prints `workspaces`, `api-keys`, `webhooks`;
  read: a new create flow has a `<Route path="x/create">` and no `Dialog` import in the list page.
- **CONV-FE-02** List pages use `ListView` and `ListViewHeader`
  (`apps/web/src/components/refine-ui/views/list-view.tsx`). The `canCreate` slot renders the
  built-in `CreateButton`, which links to the create route and is ACL-aware through
  `useCreateButton`. Do not hand-roll `PageHeader` plus a dialog. Do not modify shared
  `refine-ui` components for one page.
  Why: one list layout, one place for access control on the create action.
  Check: `grep -rln "ListView" apps/web/src/pages` prints `ApiKeysPage.tsx`, `JobsPage.tsx`, `MembersPage.tsx`, `ReceivedInvitationsPage.tsx`, `WebhooksPage.tsx`.
- **CONV-FE-03** Create pages use `CreateView` and `CreateViewHeader`
  (`apps/web/src/components/refine-ui/views/create-view.tsx`) with `useForm` from
  `@refinedev/react-hook-form` (`refineCoreProps: { resource, action: "create" }`),
  `zodResolver`, and the shadcn `Form` components. `onFinish` returns the created record and
  invalidates the list cache.
  Why: one create flow with one validation and cache behaviour.
  Check: `grep -rln "CreateView" apps/web/src/pages` and
  `grep -rln "@refinedev/react-hook-form" apps/web/src/pages` print the same two files:
  `ApiKeyCreatePage.tsx`, `WebhookCreatePage.tsx`.
- **CONV-FE-04** Navigation uses `useNavigation().list("resource")` or `useGo`, not
  react-router `useNavigate`.
  Why: Refine resolves the route from the resource name.
  Check: `grep -rln "useNavigate" apps/web/src --include=*.tsx` prints only the files listed under CONV-FE-04 in Known deviations.
- **CONV-FE-05** Data fetching uses `useList`, `useCustom` and `useCustomMutation`; custom URLs
  are relative to `/api/v1` (the dataProvider resolves them). Mutations on resources use
  `useCreate`, `useUpdate` and `useDelete`; `useCustomMutation` is for action endpoints that are
  not resource writes (for example job execute). Components do not call `fetch` or `axios`.
  Why: the dataProvider adds auth, the workspace header and error handling.
  Check: `grep -rnE "(^|[^a-zA-Z.])fetch\(|from \"axios\"" apps/web/src/pages apps/web/src/components --include=*.tsx` prints only the lines listed under CONV-FE-05 in Known deviations.
- **CONV-FE-06** Set `successNotification` in `refineCoreProps`. Set `errorNotification: false`
  when the page shows the server `detail` itself; the dataProvider already puts FastAPI
  `detail` in `error.message`.
  Why: one toast per outcome, with the server's message.
  Check: read: a form or mutation that renders its own error also sets `errorNotification: false`.
- **CONV-FE-07** API and entity types are in `apps/web/src/types.ts`. Testable logic is in a
  plain `.ts` module with no runtime imports, tested by `node --test`; shared types are imported
  with `import type`.
  Why: `node --test` cannot load `.tsx` or the `@/` alias; `types.ts` is imported by 12 files.
  Check: `cd apps/web && npm test` passes; read: a new API shape is added to `types.ts`, not declared in a page.

## CFG — configuration

Source: `apps/api/src/settings.py`, `apps/api/.env.example`, `docs/FEATURE_FLAGS.md`.

- **CONV-CFG-01** An optional backend is selected by an env var through a factory, and callers
  depend on the interface only. An unknown value raises at startup. The default is the
  development driver.

  | Backend | Env var | Factory | Default |
  |---|---|---|---|
  | event bus | `EVENT_BUS_DRIVER` | `build_event_bus` in `apps/api/src/events/factory.py` | `inprocess` |
  | secret store | `SECRET_STORE_DRIVER` | `apps/api/src/secrets/factory.py` | `db` |
  | email | `EMAIL_DRIVER` | `apps/api/src/email/factory.py` | `console` |

  Why: adopters who do not need a backend run without it (ADMISSION.md Gate 3).
  Check: `grep -rnE "settings\.(event_bus_driver|secret_store_driver|email_driver)" apps/api/src | grep -v "factory.py"` returns nothing.
- **CONV-CFG-02** A new setting is a field in `apps/api/src/settings.py` and an entry in
  `apps/api/.env.example` with a comment. Secrets are not committed.
  Why: the template file is the list of what an operator can set.
  Check: `grep -oE '^    [a-z_0-9]+ *:' apps/api/src/settings.py | tr -d ' :' | tr a-z A-Z | while read v; do grep -qE "^#? *$v=" apps/api/.env.example || echo "missing $v"; done` prints only the names listed under CONV-CFG-02 in Known deviations.
- **CONV-CFG-03** A feature flag is a workspace flag per `docs/FEATURE_FLAGS.md`: a snake_case
  key in `workspaces.flags`, default on, read as `(workspace.flags or {}).get(key) is False`.
  A new flag adds a row to the registry table and a line under "Where flags are enforced" in
  that document.
  Why: flags only disable; a missing key needs no backfill.
  Check: `grep -rnE "\.flags" apps/api/src --include=*.py` lists the flag read sites; read:
  each flag key found there has a row in `docs/FEATURE_FLAGS.md`.

---

## Known deviations

The code does not meet these rules today. Touching one of these places is a chance to fix it;
adding a new one needs a DECISIONS entry.

| Rule | Deviation |
|---|---|
| CONV-EVT-02 | `apps/api/src/services/conversations.py:746` builds the subject as `Subjects.CONVERSATIONS + ".renamed"` behind a `hasattr` fallback. The constant exists, so the fallback is dead code. |
| CONV-EVT-03 | `Subjects.CONVERSATION_CREATED` (`conversations.created`) is in `ALL`, is not published anywhere, and has no workflow. |
| CONV-API-02 | `apps/api/src/api/routes/conversations.py` builds its list queries without `apply_query`. |
| CONV-API-04 | `apps/api/src/services/profile_helpers.py`, `profiles.py` and `search_export.py` import `HTTPException`. |
| CONV-AUTH-03 | `apps/api/src/api/routes/jobs.py` (lines 237 and 280) checks `api_key.permissions` inside the route for the `/jobs/{id}` and run routes. |
| CONV-DATA-05 | `apps/api/src/api/routes/admin.py` (two routes) and `notifications.py` call `db.commit()`. |
| CONV-CFG-02 | `AUTH_IP_MAIL_MAX_ATTEMPTS` and `AUTH_IP_MAIL_WINDOW_SECONDS` are settings with no `.env.example` entry. |
| CONV-FE-01, 02, 03 | `pages/settings/workspace/sections/RolesSection.tsx` creates roles in a dialog with `useCreate`. `MembersPage.tsx` uses `ListView` but invites from an inline form with `useCreate`. `WorkspaceCreatePage.tsx` uses `PageHeader` and `useCreate` instead of `CreateView` and `useForm`. `ReceivedInvitationsPage.tsx` complies. |
| CONV-FE-04 | `useNavigate` is used in `AuthConfig.tsx`, `AppLayout.tsx`, `NotificationCenter.tsx`, `NotFoundPage.tsx`, `LoginPage.tsx`, `InvitationAcceptPage.tsx`, `WorkspaceCreatePage.tsx` and `settings/workspace/sections/GeneralSection.tsx`. |
| CONV-FE-05 | `ForgotPasswordPage.tsx`, `ResetPasswordPage.tsx` and `VerifyEmailPage.tsx` call `fetch` directly; they run before a session exists. |

## CI check candidates

Rules a script could enforce. None of these is implemented. Each becomes its own GitHub issue
with its own Gate 0 verdict ([ADMISSION.md](../product/ADMISSION.md), Gate 0); this file does
not create them.

| Rule | Proposed mechanism |
|---|---|
| CONV-EVT-02, 05, 06 | The `grep` commands above, including the `Subjects.X +` one, as one `make conventions-check` target, run in the `ci` workflow. |
| CONV-EVT-03 | Pytest test: every durable subject in `Subjects.ALL` has a registered workflow; every transient subject is in `TRANSIENT_SUBJECTS` and registered with `fanout=True`. Fails today on `CONVERSATION_CREATED` until it is fixed or removed. |
| CONV-AUTH-01 | Pytest test over each router's `routes`: every route that depends on `get_current_workspace_id` also depends on a `require_permission` or `require_key_permission` checker, with an allowlist for the routes under Known deviations and the guards named in CONV-AUTH-01. |
| CONV-AUTH-03 | `grep` in the `make conventions-check` target, with the jobs routes allowlisted until they move into `deps.py`. |
| CONV-AUTH-04 | `node --test` on `apps/web/src/App.tsx` routes: every route path outside the `/` layout is in the public set of CONV-AUTH-04. |
| CONV-AUTH-05 | `node --test`: every `resources` name in `App.tsx` that is not hidden has a `PERMISSION_MAP` key or is on an allowlist. |
| CONV-API-02, 03 | Pytest test over the app's routes: list routes set `X-Total-Count`; `DELETE` routes declare 204; create `POST` routes declare 201. |
| CONV-API-05 | Already enforced by `apps/api/tests/test_uuid_ids.py`; add a test that every `uuid.UUID`-typed path param is in `FRAMEWORK_VALIDATED_UUID_ROUTES`. |
| CONV-DATA-03, 04, 06 | `find` and `grep` commands above in the `make conventions-check` target. |
| CONV-CFG-02 | Script from the Check above, failing on any name not in `.env.example`; fix the two known names first. |
