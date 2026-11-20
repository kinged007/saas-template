# Upgrading — taking template updates

There is one supported way to start a project from this template, and one way to
update it. Other ways of starting (an unpinned download, "the latest") are not
supported for updates: linking to "the latest" instead of the pinned seed commit
produces 9–11 add/add conflicts on an unchanged tree only ten commits later
(see `docs/product/UPDATE-PATH.md` §5).

## 1. Seed from the pinned commit

1. Pick a release (see `CHANGELOG.md` / GitHub releases) and record its tag and
   commit SHA. That pair is your seed version — pin it, do not use "latest".
2. Create your project from exactly that tag (download the tag archive, or
   GitHub "Use this template" at that ref), then commit:
   `git init && git add -A && git commit -m "seed from template vX.Y.Z (<sha>)"`.
3. Link the template history, read-only — never push to it:
   ```bash
   git remote add template https://github.com/kinged007/saas-template.git
   git remote set-url --push template no-push
   git fetch template --tags
   ```

## 2. Take an update

Each update merges one release tag on its own branch:

```bash
git fetch template --tags
git checkout -b template-sync/vX.Y.Z
git merge template/vX.Y.Z
```

The first-ever sync is the one exception: your project and the template share
no history yet, so add the one-time flag
`git merge --allow-unrelated-histories template/vX.Y.Z`. Every later sync is a
plain merge, because the first sync joined the histories.

Then review before you merge to your main branch:

1. Read the release notes for the tag (sliced by area: `api` / `web` / `db` /
   `infra`), and take only the slices you want.
2. Inspect what changed since what you run:
   `git diff <previous-tag>..<tag>`.
3. Renames are announced in the release-note line (a silent rename breaks
   imports with exit 0 — see `docs/product/UPDATE-PATH.md` §3). If the notes
   announce one, update your imports to the new path.
4. If the release adds migrations, they use timestamp ids (`YYYYMMDDHHMMSS`,
   `docs/product/DECISIONS.md` D-04), so a template migration and one of yours
   never share an id. If `db-check` below reports two heads, join them with
   `alembic merge heads` and migrate again.

## 3. Verify

Run all four before merging `template-sync/vX.Y.Z` into your main branch.
Each must exit 0 — exit 0 means the project still builds and still migrates:

```bash
make db-check    # single migration head; models match migrations
make api-test    # backend tests
make web-build   # type-check + frontend build
make web-test    # frontend unit tests
```

A failure that names a file is the update stopping loudly, which is the
contract (`docs/product/VISION.md` §4, guarantee 1). Fix it on the sync
branch, re-run the four, then merge the branch and delete it.

## 4. Stable surface

The following are the template's stable API. A change that breaks any of them
requires a major version bump **and** an entry in this file saying what moved
and what adopters must do:

- the `register*` hooks,
- `EXTENSION_MODULES` and `TEMPLATE_PATHS` (`src/project/` loaders),
- the `src/project/index.ts` exports,
- `job_registry` (`apps/api/src/jobs/registry.py`),
- `WorkflowRegistry.register` (`apps/api/src/events/factory.py`),
- `EventBus` (`apps/api/src/events/bus.py`).

Note: the `src/project/` loaders (`EXTENSION_MODULES`, `TEMPLATE_PATHS`,
`src/project/index.ts`) arrive with the extension-seam issues (#1794, #1795).
This rule covers them from the release they first appear in.
