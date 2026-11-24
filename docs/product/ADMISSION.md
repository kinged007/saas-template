# Admission — how a change gets into the template

> **Status:** Proposed. Becomes binding when merged by the maintainer.
> **Applies to:** every issue, PR and agent-generated change, from anyone.
> **Derived from:** [VISION.md](VISION.md). Where they disagree, VISION wins and this file is
> the bug.

The point of this file: **a contributor, a reviewer and a coding agent, applying it
independently, reach the same verdict** — so the maintainer only has to decide the short list
in §5.

---

## 1. Run the gates in order

Stop at the first gate a change fails. Each gate names the principle it enforces.

### Gate 0 — Phase *(VISION §7)*

Until the first release, only three kinds of change are built:

- [ ] delivers an update-path guarantee (VISION §4), **or**
- [ ] fixes a security problem, **or**
- [ ] restores behaviour that is already documented (README, `docs/`, or a test).

Gate 0 is the one exception to §1 stop-at-the-first-failure rule: a change that fails it is still assessed through Gates 1–4, so the verdict names every gate it fails. Only a change that fails Gate 0 and passes Gates 1–4 is **deferred**, not built; a change that also fails a later gate gets that gate verdict (**Reject**, or **Maintainer** under §5).
A "small obvious improvement" is a new capability: it fails Gate 0, and is deferred only if it survives Gates 1–4.

### Gate 1 — Scope *(P4 Plumbing, not product)*

- [ ] It is plumbing that almost every multi-tenant B2B SaaS needs: identity, tenancy,
      authorisation, membership, API keys and machine access, audit, events, jobs, webhooks,
      feature flags, notifications, files, observability, deployment.
- [ ] It is **not** a domain feature (orders, invoices, projects, CRM, chat features…).
- [ ] It does **not** grow the demo surface (messages) beyond what is needed to exercise
      plumbing.

Fails → **Reject**. If it is plumbing but not on the list above → **Maintainer** (§5).

### Gate 2 — Update safety *(P1 Updatable, P2 Never silent, P6 Secure)*

Hard rules. Any unchecked box that can be fixed becomes a named condition (**Accept with conditions**); one with no way to fix it → **Reject**.

- [ ] **Renames, moves and deletions** of a file under `apps/` are listed in the change's
      release-note line as `old/path → new/path` (or `removed`). A silent rename breaks every
      adopter who customised that file (UPDATE-PATH §3).
- [ ] **New migrations** follow the migration-id convention ([DECISIONS.md D-04](DECISIONS.md)).
- [ ] **Edit points** (§3) are not made larger, split, moved or renamed without the edit-point
      documentation being updated in the same change.
- [ ] **Security fixes** are their own change, never bundled with refactors or redesigns, so
      an adopter can take the fix alone.
- [ ] **One area per change** — `api`, `web`, `db` or `infra`. A change spanning areas says
      why it cannot be split.
- [ ] **Authorisation** for anything workspace-scoped is enforced on the server. UI gating is
      cosmetic and never the only check.
- [ ] The squash commit into `dev` carries **one release-note line** an adopter can read to
      decide whether to take it: what changed, for whom, and anything they must do. The author
      writes it; when it is missing, the merger writes it. A missing line never blocks a merge.
      A rename, move or deletion under `apps/` that is not listed as `old/path → new/path`
      does block it.

### Gate 3 — Shape *(P3 Ownership not hooks, P5 Optional means removable)*

- [ ] No new extension framework: plugin registries, override layers, hook systems,
      "customisation points" that wrap template code. Adopters edit source; we keep the
      places they edit few and stable.
      *Exception:* an indirection that **removes** an edit point for every adopter (e.g.
      auto-discovery replacing a hand-maintained list) passes — say so in the PR.
- [ ] If not every adopter needs it, it is **off by default or removable in one sitting**:
      one documented removal, no orphaned imports, tests green afterwards.
- [ ] It follows `docs/architecture/CONVENTIONS.md`. A deviation from a `CONV-*` rule needs
      an entry in `docs/product/DECISIONS.md` that names the rule.

### Gate 4 — Quality *(P2 Never silent, P7 Clear, honest and unbranded)*

- [ ] Failures are loud and specific: no swallowed errors, no empty screens on error, no
      HTTP 200 for a failure.
- [ ] Tests state behaviour an adopter can observe, and fail if that behaviour breaks.
- [ ] Every doc touched is true when checked against the code in the same change.
- [ ] Unbranded: no credits, banners, "powered by" or marketing language.
- [ ] An engineer reading the diff cold would find nothing untrue, inconsistent or padded.

---

## 2. Verdicts

| Verdict | When | What happens |
|---|---|---|
| **Accept** | Passes every applicable gate | Built and merged in the normal flow |
| **Accept with conditions** | Passes, provided named conditions are met | Conditions go into the issue as acceptance criteria |
| **Defer** | Passes Gates 1–4, blocked only by Gate 0 | Stays open, labelled for after the first release; conditions recorded now |
| **Reject** | Fails Gate 1, or Gate 2/3 with no way to fix it | Closed with the gate and principle cited |
| **Maintainer** | Hits anything in §5 | Escalated with a recommendation; nothing is built until answered |

Every verdict names the gate and principle it rests on, in one line. *"Rejected: Gate 1 /
P4 — domain feature (invoicing) belongs in adopters' projects."*

---

## 3. Edit points

The files an adopter must edit to add a feature today. They change often, so they are where
template updates and adopter edits meet. Gate 2 protects them.

| Area | File | Lines |
|---|---|---|
| api | `apps/api/src/main.py` | 159 |
| api | `apps/api/src/models/__init__.py` | 56 |
| api | `apps/api/src/workflows/__init__.py` | 712 |
| api | `apps/api/src/settings.py` | 231 |
| api | `apps/api/src/jobs/builtin.py` | 442 |
| api | `apps/api/src/core/permissions.py` | 159 |
| web | `apps/web/src/App.tsx` | 294 |
| web | `apps/web/src/components/AppLayout.tsx` | 421 |
| web | `apps/web/src/providers/accessControlProvider.ts` | 88 |
| web | `apps/web/src/types.ts` | 404 |
| db | `apps/api/alembic/versions/` (new files only) | — |

Measured at `e435891d`: these ten files hold 2,966 lines, and are touched by a median of 20
commits each against a median of 3 for the 287 source files in `apps/*/src`. Four of them are
in the twelve most-changed source files in the repo.

**Direction:** fewer, smaller, documented. Not zero — zero needs hooks, which P3 rules out.
Each edit point gets a short "how to add your feature here" note, and that note is part of
the contract with adopters.

---

## 4. Worked examples

These calibrate the gates against real proposals. **They are illustrations of how to apply
this file, not rulings on those issues** — the issue tracker is managed separately.

**#1714 — Support derived projects that keep taking template updates.**
Gate 0 ✅ (it *is* the phase). Gate 1 ✅ (deployment/maintenance plumbing). Gates 2–4 apply to
its implementation. → **Accept.** The current priority.

**#18 — File storage abstraction (S3 + local drivers).**
Gate 0 ❌ new capability. Gate 1 ✅ files are on the plumbing list. Gate 2 ✅ if it ships its own
migrations under D-04 and its own slice. Gate 3 ✅ the issue already proposes the existing
env-selected driver pattern; condition: local driver is the default, so nothing breaks for an
adopter without S3. → **Defer**, conditions recorded.

**#549 — OpenTelemetry integration.**
Gate 0 ❌. Gate 1 ✅ observability. Gate 3: condition — inert unless configured by env; no
change to edit points beyond `settings.py`; removable in one sitting. → **Defer**, conditions
recorded.

**#1715 — MCP server for AI-assisted access.**
Gate 0 ❌. Gate 1 ✅ machine access, alongside API keys. Gate 2: condition — it must use the
same server-side permission enforcement as every route (P6); pruning tools by permission is a
requirement, not a nice-to-have. Gate 3 ✅ — building the tool catalogue from existing routes
*removes* a per-feature edit point rather than adding one; that is the exception in Gate 3
working as intended. Condition: off by default. → **Defer**, conditions recorded.

**Hypothetical — "add task boards to messages".**
Gate 1 ❌ domain feature growing the demo surface (P4). → **Reject.**

**Hypothetical — "add a plugin system so adopters can override the sidebar without editing
`AppLayout.tsx`".**
Gate 3 ❌ an override layer over an edit point; it limits redesign rather than enabling it
(P3, DECISIONS D-03). → **Reject.** The fix for a painful edit point is to make it smaller
and documented.

---

## 5. What needs the maintainer

Only these. Everything else is decided by applying this file, and the reviewer's verdict
line is the record.

1. Any change to `VISION.md`, `ADMISSION.md` or `DECISIONS.md`.
2. Adding a capability area that is not on Gate 1's plumbing list, or removing one.
3. Any change to a settled convention in `DECISIONS.md` — seed path, migration ids, release
   format.
4. Licence, repository visibility, naming, and anything the README claims publicly.
5. An exception: accepting a change that fails a gate.

When escalating: one question, the options, a recommendation and the gate that triggered it.

The maintainer merges every promotion into `main` ([DECISIONS.md D-07](DECISIONS.md)); fleet
pull requests are merged into `dev` by the merge queue once their gates pass. A merge is not,
by itself, a decision on any of the five items above — those are recorded in `DECISIONS.md`.
