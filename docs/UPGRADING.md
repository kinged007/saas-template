# Upgrading — taking template updates

There is one supported way to start a project from this template, and one way to
update it. Other ways of starting (an unpinned download, "the latest") are not
supported for updates: linking to "the latest" instead of the pinned seed commit
produces 9–11 add/add conflicts on an unchanged tree only ten commits later
(see `docs/product/UPDATE-PATH.md` §5).

## 1. Seed from the pinned commit

1. Pick a release (see `CHANGELOG.md` / GitHub releases) and record its tag and
   commit SHA. That pair is your seed version — pin it, do not use "latest".
2. Create your project at exactly that tag. Clone the tag and drop the template
   history, then commit:
   ```bash
   git clone --branch vX.Y.Z https://github.com/kinged007/saas-template.git myapp
   cd myapp && rm -rf .git
   git init && git add -A && git commit -m "seed from template vX.Y.Z (<sha>)"
   ```
   GitHub's "Use this template" is not this path: it seeds from the template's
   default branch and offers no ref selector, so it cannot pin a tag. The tag
   archive download is equivalent to the clone above. The seed carries
   `.template-version` with the template's original value — set it to your
   seed tag (`echo 'vX.Y.Z' > .template-version`) and commit it, so the
   path-check script in §2 starts from your seed.
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
git merge vX.Y.Z
```

Merge the **tag**, not `template/vX.Y.Z`: `git fetch --tags` writes the release
to `refs/tags/vX.Y.Z` and does not create a `refs/remotes/template/vX.Y.Z`
branch, so the remote-tracking name does not exist and the merge fails with
"not something we can merge".

The first-ever sync is the one exception: your project and the template share
no history yet, so add the one-time flag
`git merge --allow-unrelated-histories vX.Y.Z`. Every later sync is a plain
merge, because the first sync joined the histories.

Record the tag you just merged — `.template-version` is project-owned
(`TEMPLATE_PATHS`), so template releases never move it and the file only
advances when you advance it:

```bash
echo 'vX.Y.Z' > .template-version
git add .template-version && git commit -m "record template sync vX.Y.Z"
```

The next run of `bash scripts/check-template-paths.sh` with no arguments then
starts from this tag instead of re-reporting releases you already merged.

Then review before you merge to your main branch:

1. Read the release notes for the tag, which are grouped by area (`api` /
   `web` / `db` / `infra`) so you can see what a release touches. The merge
   itself takes the whole tag — there is no slice-taking command, and a manual
   partial port is not a supported update. If a release contains something you
   do not want, merge it anyway and revert that part in a commit of your own,
   which keeps the next merge clean.
2. Inspect what changed since what you run:
   `git diff <previous-tag>..<tag>`. For the ownership-filtered view with
   renames announced explicitly, run:
   `bash scripts/check-template-paths.sh <previous-tag> <tag>`
   (skips the project-owned paths in `TEMPLATE_PATHS`:
   `apps/*/src/project/**`, `apps/api/alembic/project_versions/**`, `.env`,
   `.template-version`).
   Then verify loudly with the four commands in §3 before merging.
3. Renames are announced in the release-note line (a silent rename breaks
   imports with exit 0 — see `docs/product/UPDATE-PATH.md` §3). If the notes
   announce one, update your imports to the new path.
4. If the release adds migrations, they use timestamp ids (`YYYYMMDDHHMMSS`,
   `docs/product/DECISIONS.md` D-04), so a template migration and one of yours
   never share an id. `db-check` below expects exactly two heads — the
   `template` head (`apps/api/alembic/versions/`) and your `project` head
   (`apps/api/alembic/project_versions/`) — so two heads is the passing
   state, not a conflict. Only merge them if you want one linear history
   again (`cd apps/api && uv run alembic merge template@head project@head`,
   which lands the merge revision in `versions/`); see `docs/MIGRATIONS.md`.

## 3. Verify

Run all four before merging `template-sync/vX.Y.Z` into your main branch.
Each must exit 0 — exit 0 means the project still builds and still migrates:

```bash
make db-check    # exactly two heads (template + project); models match migrations
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

- the `register*` hooks (`apps/api/src/project/__init__.py`, loaded via `apps/api/src/extensions.py`),
- `EXTENSION_MODULES` (env var read by `apps/api/src/extensions.py`, the API extension loader),
- `TEMPLATE_PATHS` (repo-root ownership manifest read by `scripts/check-template-paths.sh`),
- the `src/project/index.ts` exports,
- `job_registry` (`apps/api/src/jobs/registry.py`),
- `WorkflowRegistry.register` (`apps/api/src/events/factory.py`),
- `EventBus` (`apps/api/src/events/bus.py`).
