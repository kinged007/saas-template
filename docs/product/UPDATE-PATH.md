# The update path — evidence

> The measurements behind [VISION.md §4](VISION.md#4-the-central-problem-staying-updatable).
> Every figure was reproduced against `origin/main` @ `e435891d` (2026-11-16) in throwaway
> repositories; commands are in the appendix. Product and engineering each reproduced the key
> results independently. This file records **what happens today**; how to fix it is an
> engineering design, not this file.

---

## 1. Three ways to start

| Seed method | Shares template history? | Can take updates by merge? |
|---|---|---|
| `git clone` | Yes | Yes — but the adopter's project is now the template's repo, with its origin and history |
| GitHub "Use this template" | **No** | **No.** GitHub: *"Branches created from a template have unrelated histories, so you cannot create pull requests or merge between the branches."* |
| Download (ZIP / `git archive`) | **No** | **No**, same reason |

Adopters overwhelmingly start with the last two. So the update path has to work for a
project with no shared history.

## 2. Updating an unlinked project

```
$ git merge template/main
fatal: refusing to merge unrelated histories
```

Forcing it (`--allow-unrelated-histories`) turns every file both sides contain into an
add/add conflict, because there is no common ancestor:

| Adopter's project, seeded 10 commits before the update | Conflicts |
|---|---|
| Changed nothing | **11** |
| Added one router | 11 |
| Rebranded three files | 13 |

And where the template ships a security fix to a file the adopter also changed, both
one-click resolutions lose something:

| Resolution | Security fix | Adopter's change |
|---|---|---|
| keep mine (`--ours`) | **dropped** | kept |
| take template's (`--theirs`) | kept | **dropped** |

Nothing warns them either way.

## 3. Cherry-picking, and the silent rename

Cherry-picking individual template commits works better than a
merge on an unlinked project:

| Case | Result |
|---|---|
| Template changes a line the adopter didn't touch | Clean; adopter's work intact |
| Both insert at the same place | Conflict — visible, recoverable |
| **Template renames a file the adopter customised** | **Exit 0, no conflict, imports broken** |
| **Template and adopter both add migration `0021`** | **Exit 0, no conflict, database unmigratable** (§4) |

The rename case, exactly: the template renames `accessControlProvider.ts` →
`accessControl.ts` (94% similar). Git reports success, carries the adopter's content into the
new filename and removes the old path. `App.tsx` and `GeneralSection.tsx` still import the
old path, so the app no longer builds — and the error appears later, disconnected from the
update that caused it. If the file is rewritten beyond 50% similarity, git reports a
modify/delete conflict instead (exit 1), which is loud and therefore acceptable.

This is why ADMISSION Gate 2 requires every rename to be announced in the release-note line.

## 4. Migration ids collide

The template's migrations run `0001` → `0020` in one linear chain. An adopter's first
migration is naturally `0021`; so is the template's next one. The files differ in name and
content, so **no merge or cherry-pick strategy sees a conflict**. Then:

| | Sequential ids (today) | Timestamp ids (D-04) |
|---|---|---|
| `alembic heads` | `0021 (head)` twice, plus *"Revision 0021 is present more than once"* | two distinct heads |
| `alembic upgrade head` | **fails** — multiple heads | **fails** — multiple heads |
| `alembic merge heads` | **fails** — *"Duplicate head revisions specified"* | **works** |
| `upgrade head` after merge | still fails — **no recovery** | **exit 0** |

Timestamp ids do not prevent the branch; they make it **recoverable with one command**.
Two consequences for whoever designs the mechanism:

- Every call site in the repo runs `upgrade head` (singular): `Makefile`,
  `docker-compose.prod.yml`, the Helm API deployment, `scripts/db-check.sh`, the Playwright
  dev config. So either the merge step is documented as part of taking an update, or those
  call sites change. Either is acceptable; silence is not (guarantee 2).
- `make db-new` passes no `--rev-id` today, so Alembic still generates a random hex id. The
  convention needs enforcing where migrations are created, or it will decay.

The filename format already fits: `apps/api/alembic.ini` sets
`file_template = %%(rev)s_%%(slug)s`, and
`alembic revision --autogenerate --rev-id 202611171830 -m "acme orders"` produces
`202611171830_acme_orders.py` with `revision = '202611171830'`.

## 5. Linking history at seed time

If an adopter links their project to the template's history **at the exact commit they
seeded from, while their tree is still unchanged**, every later update is an ordinary
three-way merge:

| Step | Conflicts |
|---|---|
| Link the pristine download to template history at its seed commit | **0** |
| Adopter adds a router and a type; template ships a security fix touching both files | **2** (one per file), both sides visible |
| Resolve by keeping both | Fix **and** feature present |

Compare §2, where the same update forces a choice between the fix and the feature.

**The commit must be pinned.** Linking to "the latest" instead of the seed commit produced
9–11 add/add conflicts on an unchanged tree only ten commits later; on a repository this active
"the latest" moves within hours.

## 6. Prior art

| Starter / tool | Update approach | Checked |
|---|---|---|
| `fastapi/full-stack-fastapi-template` (46k stars) | **None now.** Removed Copier project generation on 2026-08-11 (#2430: deleted `copier.yml`, `.copier/`) and the "Update From the Original Template" README section (`git pull --no-commit upstream master`) on 2026-08-12 (#2442). README now says only "Use this template". | Repository history, 2026-11-18 |
| Makerkit (commercial, Next.js) | `git pull upstream main` into an update branch, resolve conflicts by hand or with an AI assistant, regenerate lockfile and types. Migrations are timestamp-named (Prisma), "so conflicts are less common". | Public "Updating your codebase" guide, 2026-11-18 |
| Copier (tool) | `copier update`: three-way merge of the template's change since the recorded version into the project; requires the project to record the template version it came from, and the template to be tagged. Conflicts inline or as `.rej` files; recommends a pre-commit hook forbidding conflict markers. | Copier docs, "Updating a project", 2026-11-18 |

Two lessons. The most popular comparable template **gave up** on updates rather than solve
them — which is the opening. And every working approach depends on the same two things this
template lacks today: **a recorded seed version** and **tagged releases**.

## 7. Updates can be sliced

Since 2026-08-20, 749 commits:

| Commit touches | Share |
|---|---|
| Backend only | 46.2% |
| Frontend only | 36.2% |
| Both | 11.1% |
| Neither (docs, CI, infra) | 6.5% |

82.4% are single-sided. Releases sliced by area match how the work is already done.

---

## Appendix — reproduction

```bash
cd saas-template && git fetch origin main
git rev-parse origin/main                    # e435891de18460e0a48a3da8478918d71dd777c8

# §1 visibility and template flag
gh api repos/kinged007/saas-template --jq '{is_template,private}'

# §2 unlinked project: 11 conflicts with zero edits
git archive <commit-10-before-main> | tar -x -C /tmp/user && cd /tmp/user
git init -q && git add -A && git commit -qm seed
git remote add template <repo> && git fetch template main
git merge --no-ff --allow-unrelated-histories template/main

# §4 migration ids (real repo, sqlite)
cd apps/api && USE_SQLITE=1 uv run --python 3.12 alembic upgrade head
#   add two revisions, both down_revision="0020":
#   ids "0021"/"0021"                 -> merge heads fails: Duplicate head revisions
#   ids "202611171830"/"202611171905" -> merge heads works; upgrade head exit 0
USE_SQLITE=1 uv run --python 3.12 alembic revision --autogenerate \
  --rev-id 202611171830 -m "acme orders"

# §7 slicing
git log --since=2026-08-20 --name-only --pretty=format:__C__

# Edit-point churn (ADMISSION §3): non-merge commits per file over all history;
# the ten edit points have a median of 20 touches, the 287 files in apps/*/src a median of 3.
```

## Corrections log

Figures earlier drafts got wrong, kept so nobody reuses them:

| Earlier figure | Correct | Why it was wrong |
|---|---|---|
| "245 of the last 600 commits touch the ten edit points" | 130 of 752 non-merge commits, all history; median 20 touches per edit point vs 3 per source file | Per-file commit logs were summed, double-counting commits and not limiting to 600 |
| Edit points total 3,054 lines | 2,966 at `e435891d` | Measured on a different checkout |
| Rename "deletes the adopter's file" | Moves it silently and breaks imports | Mis-read the result; engineering reproduced the correct behaviour |
| Linked-history update: 1 conflict | 2 (one per edited file) | Miscounted |
| 0 tags | 1 tag, machine-generated, not a release; 0 releases | Stale count |
