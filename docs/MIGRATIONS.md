# Database migrations

Alembic owns the schema. Models are the source of truth; migrations are
generated, reviewed, committed. Day-to-day flow never changes — PRs keep
appending migrations exactly like now.

## Daily workflow

Change models, then generate (14-digit UTC timestamp id per DECISIONS D-04; make db-new does not set the id yet, so do not use it until it does):

```bash
cd apps/api && uv run alembic revision --autogenerate --rev-id "$(date -u +%Y%m%d%H%M%S)" -m "add index on users.email"
```

**Review the generated diff before committing.** Autogenerate catches
tables, columns, indexes, constraints — it does not judge intent. Check
for: accidental drops (renamed model attribute looks like drop+add),
wrong nullability on existing columns (needs a data backfill first),
missing `server_default` on NOT NULL columns added to populated tables.

Merge conflicts on `versions/`: two PRs branching a migration off the same
parent produce two heads. `make db-check` fails CI — the later-merged PR
repoints its `down_revision` to the new head. One line.

## Indexes

An index needs three things before it becomes a migration: the access path it
serves, a measurement showing that path is slow, and the write cost it adds.
The measurement goes in this file so the next reader does not repeat it.

### `notifications`: no composite `(user_id, workspace_id)`

The list, unread-count and bulk paths scope on `user_id` **and** `workspace_id`,
which is what a composite would serve. The by-id paths instead key on `id`
and add `workspace_id` only when the caller sends one. Every runtime access
path:

| Path | Predicates | Index used |
| --- | --- | --- |
| `GET /notifications` rows and its `COUNT(*)` (`apps/api/src/api/routes/notifications.py:81`) | `user_id`, `workspace_id`, `ORDER BY created_at DESC, id DESC` | `ix_notifications_user_id` + `ix_notifications_workspace_id` (BitmapAnd) |
| `GET /notifications/unread-count`, `PATCH /notifications/read-all` | `user_id`, `workspace_id`, `acknowledged_at IS NULL`, `type <>` | `ix_notifications_user_id` + `ix_notifications_workspace_id` (BitmapAnd) |
| `acknowledge_for_conversation` (`apps/api/src/services/notifications.py:279`) | `user_id`, `workspace_id`, `type =`, `acknowledged_at IS NULL` | `ix_notifications_user_id` + `ix_notifications_workspace_id` (BitmapAnd) |
| `PATCH /notifications/{id}`, `DELETE /notifications/{id}` (`apps/api/src/services/notifications.py:456`, `apps/api/src/api/routes/notifications.py:219`) | `id`, `user_id`, optional `workspace_id` | primary key |
| global search (`apps/api/src/services/search_export.py:288`) | `workspace_id`, `user_id`, `title/body ILIKE` | `ix_notifications_user_id` + `ix_notifications_workspace_id` (BitmapAnd) |
| digest (`apps/api/src/jobs/builtin.py:178`), GDPR count (`apps/api/src/services/profiles.py:294`) and delete (`apps/api/src/services/profiles.py:366`, `apps/api/src/services/profiles.py:435`) | `user_id` | `ix_notifications_user_id` |
| workspace JSON export (`apps/api/src/services/search_export.py:426`) | `workspace_id` | `ix_notifications_workspace_id` |
| workspace delete, via the `WORKSPACE_CASCADE` registry (`apps/api/src/services/workspaces.py:351`, `apps/api/src/db/cascade.py:31`) | `workspace_id` | `ix_notifications_workspace_id` |
| retention cleanup (`apps/api/src/jobs/builtin.py:244`) | `acknowledged_at IS NOT NULL`, `created_at <` cutoff | none, seq scan |

Measured on embedded Postgres at 1M rows (50 workspaces × 100 users, each user
with 200 notifications spread across two of those workspaces, 327 MB,
`VACUUM ANALYZE`d, `EXPLAIN (ANALYZE, BUFFERS)`), for a typical user — 200
rows, 100 of them in the queried workspace, so
`ix_notifications_workspace_id` matches 10,000 of the 1M entries. Ordering is
`_NOTIFICATION_DEFAULT_ORDER` (`apps/api/src/api/routes/notifications.py:39`);
the limit is the caller's (`spec.limit`,
`apps/api/src/api/routes/notifications.py:92`, default 10, capped at 100) and
the runs below asked for 50:

| Query | Two single-column indexes | With composite |
| --- | --- | --- |
| list rows, `ORDER BY created_at DESC, id DESC LIMIT 50` | BitmapAnd, 200 + 10,000 index entries, 1.1–3.9 ms | Index Scan, 100 entries, 0.2–1.4 ms |
| its `COUNT(*)` subquery | BitmapAnd, 200 + 10,000 entries, 1.1 ms | Index Only Scan, 5 buffers, 0.13 ms |
| `unread_count` | BitmapAnd, 200 + 10,000 entries, 1.8 ms | Index Scan, 100 entries, 0.25 ms |
| retention cleanup | Seq Scan over the whole table | Seq Scan, unchanged |

The spread in the list row is cold vs warm cache. The `Index Only Scan` is a
property of the freshly `VACUUM`ed table — acknowledging or reading all
notifications dirties the heap, so in production that row degrades to an
`Index Scan` with heap fetches. Every read is already served by an index and
returns in milliseconds, so nothing is slow. The composite reads 100 index
entries where the current plan reads ~10,200 — a constant factor on a path
that does not need it, paid for with an index write per insert.
`PATCH /notifications/read-all` and `acknowledge_for_conversation` are writes
rather than reads, but they find their rows through the same `BitmapAnd`, so
they pay that ~10,200-entry scan on every call too.

Decision: no composite. `ix_notifications_workspace_id` stays regardless —
the workspace JSON export filters on `workspace_id` alone, and so does the
delete `delete_workspace` runs over the `WORKSPACE_CASCADE` registry for
every model it lists (`Notification` included). Both keep planning through it.

Revisit when a slow-query log or `EXPLAIN` shows one of those reads scanning
more than ~1k index entries for a single request, one user passes ~10k rows,
or the table passes ~5M rows. Then it is a **swap, not an addition**:
`ix_notifications_user_id` is a leftmost prefix of the composite and becomes
redundant, so drop it in the same migration and the index count and write cost
stay flat. Nullability is not part of that argument: a btree's leading column
serves the `user_id`-only paths whether or not `workspace_id`
(`apps/api/src/models/core.py:68`) is `NOT NULL`.

Models are the source of truth, so the model moves first (`Notification`,
`apps/api/src/models/core.py:61`): drop `index=True` from `user_id` — that
flag is what produced `ix_notifications_user_id`
(`apps/api/alembic/versions/0001_initial.py:128`) — and declare the composite
in `__table_args__`, the shape `Message` already uses
(`apps/api/src/models/conversation.py:55`), and add `Index` to the
`sqlalchemy` import at `apps/api/src/models/core.py:6`, which does not have
it yet:

```python
class Notification(Base, TimestampMixin):
    __table_args__ = (
        Index("ix_notifications_user_workspace", "user_id", "workspace_id"),
    )

    user_id: Mapped[str] = mapped_column(StringUUID(), index=False, nullable=False)
```

Then `make db-new m="composite notifications (user_id, workspace_id)"`.
Skipping the model half is what fails CI: with `index=True` still on `user_id`,
autogenerate re-creates `ix_notifications_user_id`, `scripts/db-check.sh` finds
the `op.` call in the generated file and reports `FAIL: models differ from
migrations`.

Autogenerate emits the two ops plainly, and in the wrong order — drop first,
create second. Replace the pair with the `CONCURRENTLY` form below, which it
never emits. On a large table the plain pair takes a `ShareLock` that blocks
notification inserts for the duration, and the table grows without bound
because retention purges only acknowledged rows. Order matters — create the
composite first and drop the old index only once the new one is valid, because
a failed `CREATE INDEX CONCURRENTLY` leaves an `INVALID` index that has to be
dropped by hand before a retry. Guard it like every other Postgres-only op in
`versions/`, since SQLite test databases are built by `create_all`
(`apps/api/tests/conftest.py`) rather than by replaying the chain:

```python
bind = op.get_bind()
pg = bind.dialect.name != "sqlite"
if pg:
    with op.get_context().autocommit_block():
        op.create_index(
            "ix_notifications_user_workspace",
            "notifications",
            ["user_id", "workspace_id"],
            postgresql_concurrently=True,
        )
        op.drop_index(
            "ix_notifications_user_id",
            table_name="notifications",
            postgresql_concurrently=True,
        )
```

The generated `downgrade()` is the inverse already — drop the composite,
recreate `ix_notifications_user_id` — and on a large table it wants the same
`CONCURRENTLY` treatment; check `insp.get_indexes()` before recreating, as
`0013_converge_historical_drift.py` does, so a retry of a half-applied
downgrade does not fail on an index that is already there.

Two paths no index here fixes. The retention cleanup is a seq scan over the
whole table; a partial index on `created_at WHERE acknowledged_at IS NOT
NULL`, or a batched delete, is that fix. And
`acknowledge_for_conversation` (`apps/api/src/services/notifications.py:279`)
selects every unread `conversation_message` row for the user and workspace,
then filters `payload["conversation_id"]` in Python, so it materializes the
whole unread backlog per call — a composite `(user_id, workspace_id)` returns
exactly those same rows and does not help. At the trigger above that is the
path that breaks first; it needs a real `conversation_id` column, or the
payload filter pushed into SQL.

The unread paths have a cheaper option than the composite: a partial index
`(user_id, workspace_id) WHERE acknowledged_at IS NULL` serves
`GET /notifications/unread-count` and `PATCH /notifications/read-all`. It is
not the swap, because the GDPR count filters on `user_id` alone and a partial
index cannot serve it, so `ix_notifications_user_id` would stay and the index
count and write cost would rise rather than stay flat.

## Checks

```bash
make db-check     # single head + autogenerate-empty on a scratch DB
make db-history   # show the chain
```

`db-check` migrates a scratch embedded postgres to head, then asserts
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
delete their file if the change is already in the baseline). Consumers
upgrading past a squash: their `alembic_version` names a deleted revision —
`stamp` to the baseline, then `upgrade head`. Document the stamp target in
the release notes.

## Fresh installs vs upgrades

- Fresh: `create_all` + `alembic stamp head` + seed (no replay).
- Update: `alembic upgrade head` only.
- Never `create_all` at app startup: hides drift, races replicas, needs
  elevated DB privileges.
