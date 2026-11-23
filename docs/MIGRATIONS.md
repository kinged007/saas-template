# Database migrations

Alembic owns the schema. Models are the source of truth; migrations are
generated, reviewed, committed. Day-to-day flow never changes — PRs keep
appending migrations exactly like now.

## Daily workflow

Change models, then generate (14-digit UTC timestamp id per DECISIONS D-04):

```bash
make db-new m="add index on users.email"
```

This writes `apps/api/alembic/versions/<YYYYMMDDHHMMSS>_<slug>.py` with a
matching `revision` id.

**Review the generated diff before committing.** Autogenerate catches
tables, columns, indexes, constraints — it does not judge intent. Check
for: accidental drops (renamed model attribute looks like drop+add),
wrong nullability on existing columns (needs a data backfill first),
missing `server_default` on NOT NULL columns added to populated tables.

Merge conflicts on `versions/`: two PRs branching a migration off the same
parent produce two heads. `make db-check` fails CI — the later-merged PR
repoints its `down_revision` to the new head. One line.

## Two branches: template + project

Template migrations stay linear in `apps/api/alembic/versions/`. Project
migrations live in `apps/api/alembic/project_versions/` on the `project`
branch, so a project revision id can never collide with a template one:

```bash
make db-new-project m="acme orders"
```

This writes
`apps/api/alembic/project_versions/<YYYYMMDDHHMMSS>_<slug>.py` with
`branch_labels = "project"` and `down_revision = None` — a separate root on
purpose — plus `depends_on` pointing at the template revision it needs (the
current `template@head` for the first project migration; later ones descend
from `project@head`, which already carries that ordering transitively).
`alembic heads` then reports exactly two heads, and
`alembic upgrade heads` applies both branches, template first.

`make db-check` passes with exactly those two heads and fails on one or on
three or more. If you ever want one linear history again, merge the branches
— the merge revision lands in `versions/`:

```bash
cd apps/api && uv run alembic merge template@head project@head
```

## Checks

```bash
make db-check     # template + project heads, autogenerate-empty on a scratch DB
make db-history   # show both branches
```

`db-check` migrates a scratch embedded postgres to both heads, then asserts
`alembic revision --autogenerate` produces no `op.*` calls — i.e. no
"changed models, forgot migration" (checks 1–2). It also migrates a scratch
SQLite file and pins the check-constraint names the chain lands on both
dialects (check 3, below). It runs in CI on every PR. It never touches your
dev database (`EMBEDDED_DB_DIR` points at a temp dir).

Known limitation: `env.py` disables `compare_type` / `compare_server_default`
(legacy VARCHAR-vs-String spellings render as phantom drift). Silent column
narrowings are not caught — reviewers check type changes by eye.

### Dialect branches (SQLite vs Postgres)

SQLite cannot `ALTER` a table to add or drop a constraint, so such a migration
branches on `bind.dialect.name` and takes the SQLite path through
`op.batch_alter_table()`. The naming convention in `src/db/base.py`
(`ck_%(table_name)s_%(constraint_name)s`) applies to the name of every
check-constraint operation — batch and plain paths alike — so passing the full
name doubles it to `ck_refresh_tokens_ck_refresh_tokens_revoke_reason` on both
dialects. Every path therefore passes the bare suffix and the constraint lands
on the clean `ck_refresh_tokens_revoke_reason`; the models spell the bare
suffix too, so `create_all` and squash baselines land the same name. See
`0020`:

```python
_SUFFIX = "revoke_reason"
_CONSTRAINT = f"ck_refresh_tokens_{_SUFFIX}"
```

`db-check` check 3 migrates the chain on SQLite and on the scratch Postgres
and asserts the exact check-constraint name set on both dialects — extend that
assert when your migration adds a check constraint. The assert survives
squashing: a baseline has no dialect branches, and its `create_table` names
render off the models through the same convention, so they land the same clean
names.

## Release squashes

Don't enforce the full dev sequence on template consumers. At release
boundaries (or ~10 migrations), squash `versions/` to one baseline:

```bash
make db-squash m="baseline schema"
```

The order matters, and getting it wrong is silent. `alembic revision
--autogenerate` diffs the **live database** against the models, not the
migration chain, so migrating the database to head first makes the diff
empty by construction — a "baseline" with zero `op.*` calls that creates no
schema at all. And on a genuinely empty database autogenerate refuses to run
(`Target database is not up to date`), because `alembic_version` is absent
while the chain's head exists. `make db-squash` therefore stamps `head` onto
the empty database first, which writes the version row without running any
migration, so the guard passes while the database is still empty.

`db-squash` then proves the result instead of trusting it, on throwaway
embedded postgres instances (`EMBEDDED_DB_DIR` in a temp dir — your dev
database is never touched):

1. the baseline alone must reproduce the schema,
2. the old chain must still reach the same schema,

each checked by autogenerating against it and requiring zero `op.*` calls.
Either failure leaves `versions/` untouched. It also rewrites what
autogenerate cannot emit correctly: `down_revision = None` on `0001` (it
would otherwise point at the head being replaced), and the import of
`src.db.base` (alembic renders a custom column type as the dotted path to its
class and never emits the matching import, so the file would not import as
generated). The generated `downgrade()` is kept as-is — it already drops
every table, which is what a baseline should do. The baseline is then linted
with `uv run --extra dev ruff format` / `ruff check --fix`, which sync the dev
extra on demand and therefore need PyPI reachable on a checkout that has not
run `make api-install`; if ruff cannot run or reports an unfixable diagnostic,
the squash aborts and restores the old chain instead of shipping a baseline CI
would reject.

Known limitation: `env.py` disables `compare_type` / `compare_server_default`,
so both proofs confirm tables, columns, indexes and constraints — not that
every column kept its exact type and server default. Review type changes in
the squashed diff by eye, as with any migration.

Open PRs that branched pre-squash repoint `down_revision` to `0001` (or
delete their file if the change is already in the baseline).

A squash replaces the template chain, so every project revision's
`depends_on` dangles afterwards — until it is repointed, every alembic
command fails while loading the revision map. Repoint each `depends_on` to
the new baseline in the same change. Consumers upgrading past a squash stamp
to the baseline, then upgrade both heads (`alembic stamp heads &&
alembic upgrade heads`), stamping only the branches their database already
reflects — a database that never applied the project branch upgrades it
instead of stamping it. Document the stamp target in the release notes.
`make db-squash` itself never changes `project_versions/` content: it only
moves the files aside for the baseline proof and restores them.

## Legacy `usage_quota = 0` rows

Keys stored with `usage_quota = 0` before the #948 guard are dead, not
broken: every use is refused with 403, and `PATCH /api-keys/{id}` with a
positive quota (or `null` for a deliberately unlimited key) revives them.
Do not migrate them — `NULL` is the unlimited sentinel, so
`UPDATE api_keys SET usage_quota = NULL WHERE usage_quota = 0` would turn
every dead credential into an unlimited one, and any positive replacement
is arbitrary.

Runbook query to find them:

```sql
SELECT id, workspace_id, name, usage_quota FROM api_keys WHERE usage_quota = 0;
```

A `CHECK (usage_quota IS NULL OR usage_quota >= 1)` rejects violating rows
rather than repairing them, so it cannot land until the count above is
known and decided — it belongs in the same migration as that decision, not
before it. The schema guard (`QuotaAtLeastOne`) carries the full policy.

## Fresh installs vs upgrades

- Fresh: `create_all` + `alembic stamp heads` + seed (no replay).
- Update: `alembic upgrade heads` only.
- Never `create_all` at app startup: hides drift, races replicas, needs
  elevated DB privileges.
