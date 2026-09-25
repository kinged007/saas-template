# Database migrations

Alembic owns the schema. Models are the source of truth; migrations are
generated, reviewed, committed. Day-to-day flow never changes — PRs keep
appending migrations exactly like now.

## Daily workflow

Change models, then generate:

```bash
make db-new m="add index on users.email"
```

**Review the generated diff before committing.** Autogenerate catches
tables, columns, indexes, constraints — it does not judge intent. Check
for: accidental drops (renamed model attribute looks like drop+add),
wrong nullability on existing columns (needs a data backfill first),
missing `server_default` on NOT NULL columns added to populated tables.

Merge conflicts on `versions/`: two PRs branching a migration off the same
parent produce two heads. `make db-check` fails CI — the later-merged PR
repoints its `down_revision` to the new head. One line.

## Checks

```bash
make db-check     # single head + autogenerate-empty on a scratch DB
make db-history   # show the chain
```

`db-check` migrates a scratch embedded postgres to head, then asserts
`alembic revision --autogenerate` produces no `op.*` calls — i.e. no
"changed models, forgot migration". It runs in CI on every PR. It never
touches your dev database (`EMBEDDED_DB_DIR` points at a temp dir).

Known limitation: `env.py` disables `compare_type` / `compare_server_default`
(legacy VARCHAR-vs-String spellings render as phantom drift). Silent column
narrowings are not caught — reviewers check type changes by eye.

## Release squashes

Don't enforce the full dev sequence on template consumers. At release
boundaries (or ~10 migrations), squash `versions/` to one baseline:

```bash
make db-squash m="baseline schema"
```

The script autogenerates the baseline against an empty DB, then proves it
twice before it will touch anything: the baseline alone must reproduce the
schema, and the old chain must reach the same schema. Both checks run
autogenerate on a scratch DB and require zero `op.*` calls. It refuses to
run with uncommitted changes under `versions/`, and the old revisions end up
in git history rather than the tree.

Doing it by hand instead:

```bash
cd apps/api
uv run alembic stamp head                      # empty DB, so autogenerate emits creates
uv run alembic revision --autogenerate --rev-id 0001 -m "baseline schema"
# set down_revision = None, move the old files away,
# upgrade an empty DB, autogenerate again — must be empty
```

Open PRs that branched pre-squash repoint `down_revision` to the new
baseline (or delete their file if the change is already in it). Consumers
upgrading past a squash: their `alembic_version` names a deleted revision —
`stamp` to the baseline, then `upgrade head`. Document the stamp target in
the release notes.

A squashed tree has one revision, so two branches that both append a
migration collide on filename rather than revision id, and a duplicate
`revision = "0011"` (which git merges silently, because the filenames
differ) becomes impossible.

## Fresh installs vs upgrades

- Fresh: `create_all` + `alembic stamp head` + seed (no replay).
- Update: `alembic upgrade head` only.
- Never `create_all` at app startup: hides drift, races replicas, needs
  elevated DB privileges.
