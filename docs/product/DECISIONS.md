# Product decisions

> Settled decisions about what the template is and how it changes. Reviewers cite these by
> ID. Changing one needs the maintainer
> ([ADMISSION.md §5](ADMISSION.md#5-what-needs-the-maintainer)).
>
> **Status:** Proposed. D-01 to D-06 are already agreed; this file becomes their canonical
> record when merged. Open items are at the bottom and are **not** decided.

---

## D-01 — A base to build on, not a product

**Accepted:** 2026-11-17

**Decision:** The template is a starting base. Adopters copy it — by download or "Use this
template" — and build their own product on top. It deploys as-is: sign-up, workspaces and
member messaging all work, so the plumbing can be exercised and tested end to end. That
surface is a test bed. It is not a product, and it does not gain end-user features.

**Means:** VISION §1–§2 and P4. Proposals that make the demo surface more useful to an end
user are rejected.

---

## D-02 — Adopters get full flexibility

**Accepted:** 2026-11-17

**User story:** *As an adopter, I can change anything in the template — redesign the UI,
restructure navigation, rewrite core flows — and still choose which parts of each template
update to bring into my project.*

**Decision:** No part of the template is off-limits to change. Updates are delivered in
pieces, split first into frontend and backend and then by feature, so an adopter takes only
what they want.

**Means:** P3 (ownership, not hooks) and update guarantee 3 (takeable in pieces).

---

## D-03 — No core package with extension hooks

**Accepted:** 2026-11-17 · follows from D-02

**Decision:** The template is not shipped as an importable core package customised through
hooks. It covers too much ground for hooks to anticipate every change an adopter will make,
so the hook set would become the boundary of what adopters can do — the limitation D-02
rules out.

**Means:** ADMISSION Gate 3. Edit points are kept few, small, stable and documented instead.

---

## D-04 — Migration ids are timestamps with a slug

**Accepted:** 2026-11-17

**Decision:** Every new migration's revision id is a timestamp, and its filename is
`<timestamp>_<short_slug>.py` (for example `<timestamp>_acme_orders.py`). Independently
authored timestamps do not collide; sequential numbers do, because the template and every
adopter count from the same last number.

Tested against real Alembic on this repository before adoption: with sequential ids a
template/project collision is **unrecoverable** (`alembic merge heads` fails with "Duplicate
head revisions"); with timestamp ids it is **recoverable** with one `alembic merge heads`.
Evidence: [UPDATE-PATH.md §4](UPDATE-PATH.md#4-migration-ids-collide).

**Means:** the filename format is already set by `file_template` in `apps/api/alembic.ini`;
only the id changes. Existing migrations `0001`–`0020` are not renumbered.

**Format:** fourteen digits, `YYYYMMDDHHMMSS` in UTC — for example
`20261118104500_acme_orders.py`. A ten-digit id (`YYYYMMDDHH`) is one hour wide, so two
migrations created in the same hour would share it, which is the unrecoverable case this
decision exists to remove. Fourteen digits narrows the window to one second. Width accepted
2026-11-18. The one exception is the squashed release baseline, which `make db-squash` writes as `alembic/versions/0001_<slug>.py` with `revision = "0001"` (see `docs/MIGRATIONS.md`).

`make db-new` does not generate these ids yet; until it does, pass the id explicitly
(see `AGENTS.md`, Migrations).

---

## D-05 — Updatable first, then features

**Accepted:** 2026-11-18

**Decision:** Until the first release, work goes into making the template updatable. New
feature development resumes after it.

**Means:** VISION §7 and ADMISSION Gate 0. Until the first release: update-path work,
security fixes and fixes restoring documented behaviour. New capabilities are assessed and
deferred.

---

## D-06 — The documentation decides; only the short list escalates

**Accepted:** 2026-11-18

**Decision:** VISION and ADMISSION are the shared reference for contributors, reviewers and
coding agents. A change that is consistent with them is accepted by applying them; it does
not need individual sign-off. Only the items in ADMISSION §5 go to the maintainer.

**Means:** the reviewer's verdict line is the record of each decision.

---

## Open — not decided

### O-1 — Repository visibility

Measured 2026-11-17 18:16 CET: `private: true`, `is_template: false`. While private, nobody
can adopt it, so D-01 cannot be met. "Use this template" is also unavailable until the
template flag is set.

**Status (2026-11-18): deferred.** The repository stays private until the clean-up before the
first release is done. Visibility and the template flag change together at that point.
