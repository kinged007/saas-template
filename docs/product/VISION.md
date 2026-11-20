# Product Vision

> **Status:** Proposed. Becomes binding when merged by the maintainer.
> **Owner:** Product · **Last measured against:** `origin/main` @ `e435891d` (2026-11-16)
> **Read with:** [ADMISSION.md](ADMISSION.md) (how changes are accepted) ·
> [DECISIONS.md](DECISIONS.md) (what is settled, and by whom) ·
> [UPDATE-PATH.md](UPDATE-PATH.md) (the evidence behind §4)

This document says what the template is for. It is the reference every contributor,
reviewer and coding agent uses to decide whether a change belongs. If a change cannot be
justified from this page, it does not belong — however good it is.

---

## 1. What this is

> **A multi-tenant SaaS base a competent engineer can adopt, reshape without limit, and keep
> pulling improvements from — without their project rotting the moment they start.**

Three verbs, and the third one is the product:

| Verb | What it takes | Status |
|---|---|---|
| **Adopt** | A working, tested, tenant-aware core on day one | Built |
| **Reshape** | Every file is the adopter's to change — layout, menus, flows, even the design system | True by construction: it is source, not a package |
| **Keep pulling** | Template improvements (security first) reach a project that has diverged | **Not yet true.** This is the open problem and the current priority (§4) |

Adopting a starter is easy. **Staying adoptable is the product.** Any change that makes the
template better while making it harder to stay current is a net loss.

### What it is not

- **Not a product on its own.** It deploys, accepts sign-ups and lets members message each
  other — to demonstrate and test the plumbing. There is nothing for an end user to *do*, and
  that is deliberate. Nobody should add features to make the demo app useful.
- **Not a framework or a package.** No core library with extension hooks. Hooks cover the
  seams someone anticipated; "redesign the menu structure" is not a seam. (Rejected —
  [DECISIONS.md D-03](DECISIONS.md).)
- **Not a fork target.** Adopters download it, or use "Use this template". The update story
  must work for a project that does **not** share the template's git history.

---

## 2. Who it is for

**The adopter.** A senior engineer, or a team of two or three, starting a
multi-tenant B2B SaaS, who will still own this codebase in 18 months.

- **Their story:** *As an adopter, I want to reach the feature that makes my product
  different without first rebuilding tenancy, authorisation, invitations, API keys, audit and
  jobs — and without painting myself into a corner.*
- **The moment that decides whether we served them:** their **first template update**, months
  after they started, on a codebase they have changed heavily. Not `make setup`. Day one is
  easy to win; month six is where every starter loses them.
- **What they already know:** git, FastAPI, React, SQL migrations. Write for them. Do not
  explain git; do explain anything specific to this template.

---

## 3. Why this one — the position

There are good starters. The gap between them is not features; it is what happens after
day one.

| | `fastapi/full-stack-fastapi-template` | Makerkit (commercial, Next.js) | **This template** |
|---|---|---|---|
| Multi-tenant (workspaces, RBAC, invitations, API keys) | No — its models are `User` + `Item`, with an `is_superuser` flag | not inspected¹ | **Yes** |
| Audit trail, event bus, DB-backed jobs, signed webhooks, feature flags | No | not inspected¹ | **Yes** |
| Documented way to take template updates | **Removed** — Copier generation deleted 2026-08-11 (#2430); upstream-update instructions deleted 2026-08-12 (#2442) | Yes — `git pull upstream main`, resolve conflicts by hand or with AI | **Not yet — this is the bet** |
| Works when adopted via "Use this template" / download | Adopt only; no update path | Assumes git upstream remote | **Must** (§4) |

¹ Only Makerkit's public update guide was read; its feature set was not inspected and no claim is made about it.
Sources and dates: [UPDATE-PATH.md §6](UPDATE-PATH.md#6-prior-art).

**The position, in one line:**

> *Other starters give you a head start. This one gives you a base you can keep.*

That line is a promise the template does not keep yet. It is published only when §4's
guarantees are true and released. Until then the README makes no claim about updates.

**Who we are not for**, so nobody builds for them: people who want a no-code or low-code
builder; people who want a hosted product; people who want a minimal single-user scaffold
(the FastAPI template serves them well); people who want the template to own their domain
model.

---

## 4. The central problem: staying updatable

Measured, not assumed — full evidence and reproduction in [UPDATE-PATH.md](UPDATE-PATH.md).

1. **How an adopter starts decides everything.** A downloaded or "Use this template" project
   has no shared history with the template. Updating it forces **11 conflicts with zero user
   edits**. The same project linked to the template's history *at the exact commit it was
   seeded from, before any edits* gets **0** — and a later security update to two customised
   files produces **2 conflicts where both sides are visible and both survive**.
2. **Two failures are silent today.** An update that renames a file the adopter customised
   exits 0 and leaves their imports pointing at a path that no longer exists. A template
   migration and a project migration can both claim `0021`; git reports success and the
   database becomes unmigratable with no recovery command.
3. **Updates can be taken in pieces.** 82.4% of 749 commits since 2026-08-20 touch only the
   backend or only the frontend. Slicing releases by area matches how the work is already
   done.

### The guarantees — in priority order

Every update mechanism, release and change to the template must keep these. They are the
acceptance criteria for "updatable".

1. **No silent breakage.** An update either applies cleanly or stops loudly, naming the file
   and the problem. Exit 0 must mean the project still builds and still migrates.
2. **Always a named recovery.** Every failure an update can cause has a documented command
   that gets the adopter back to a working state. A recoverable failure is acceptable; a
   terminal one is a release blocker.
3. **Takeable in pieces.** Every release is a short list of slices — each with one area
   (`api` / `web` / `db` / `infra`), one purpose and one line of release notes — so an adopter
   can take the security slice without the redesign slice.
4. **One supported way to start.** There is exactly one documented seed path, and it links
   to template history at the pinned seed commit. Other ways of starting are not supported for
   updates, and the docs say so plainly.

**How** these are delivered — tooling, release format, numbering — is engineering's to design.
This document sets what must be true, not how.

---

## 5. Principles

Each principle ends with the question a reviewer asks. [ADMISSION.md](ADMISSION.md) turns
them into a checklist.

**P1 — Staying updatable beats getting better.**
A regression in the update path outranks any feature. A feature that widens the gap between
what adopters have and what the template has waits until the gap can be crossed.
*Does this make the next update harder for someone who has already adopted?*

**P2 — Never fail silently.**
Errors are loud, specific and recoverable — in the update path, the API and the UI. Exit 0,
HTTP 200 and an empty screen must each mean "it worked".
*If this goes wrong, will the person know, and will they know what to do?*

**P3 — Flexibility through ownership, not hooks.**
The adopter owns every file. We do not build extension frameworks, plugin registries or
override layers to "protect" them from editing. Instead, the places an adopter must edit to
add a feature (the *edit points*) are **few, small, stable and documented**, so their edits
merge cleanly with ours.
*Does this add an edit point, move one, or make one bigger? If so, is it documented?*

**P4 — Plumbing, not product.**
The template contains what every multi-tenant B2B SaaS needs and nobody differentiates on:
identity, tenancy, authorisation, membership, keys, audit, events, jobs, webhooks, flags,
notifications, files, observability. Domain features belong in adopters' projects. The demo
surface (messages) exists to exercise the plumbing, not to grow.
*Would almost every adopter otherwise build this themselves, in roughly this shape?*

**P5 — Optional means removable.**
A capability not every adopter needs must be off by default or deletable cleanly: one
documented removal, no orphaned references, tests still green.
*Can an adopter who doesn't want this get rid of it in one sitting?*

**P6 — Secure by default; the server is the authority.**
Permissions are enforced server-side on every workspace-scoped route; the UI only reflects
them. Security fixes are the main reason adopters take updates, so they ship as their own
slices and are never bundled with redesigns.
*Is this enforced on the server, and could a security fix to it be taken on its own?*

**P7 — Clear, honest and unbranded.**
Consistent patterns over clever ones. Tests that state behaviour. Docs that are true when
checked. History that explains itself. The adopter inherits every line, so nothing in the
template needs stripping out before they ship their own product: no credits, banners,
"powered by" or marketing copy.
*Would an engineer inheriting this code find anything untrue, inconsistent, padded, or that
they would have to remove?*

---

## 6. How we know it's working

| Measure | Now (2026-11-16, `e435891d`) | Target |
|---|---|---|
| Silent failures in the update path | **2** | **0** before the first release |
| Update failures with no recovery command | **1** (migration-id collision) | **0** before the first release |
| Conflicts on update, adopter changed nothing, supported seed path | **0** linked / **11** unlinked | 0 — and the supported path is the documented one |
| Releases published | **0** (one machine-generated tag, not a release) | First release when the targets above are met |
| Release notes broken into area slices | n/a | 100% of releases |
| Edit points — documented | 0 of 10 | 10 of 10 |
| `make setup` → running app, clean machine | Not yet measured | Measured each release |

**North star:** *An adopter can take the template update they choose, know exactly what it
changes, and end with a project that builds and migrates.*

Feature count, stars and route count are deliberately not on this table. More features
are not progress unless the update path carries them.

---

## 7. Current phase

**Phase: make it updatable.** In force from 2026-11-18 until the first release.

Agreed 2026-11-18 ([DECISIONS.md D-05](DECISIONS.md)).

Until the first release, the template accepts:

1. Work that delivers the §4 guarantees (seed path, migration-id convention, release slicing,
   documented edit points).
2. Security fixes.
3. Bug fixes that restore already-documented behaviour.

New capabilities are **deferred, not rejected**: they are assessed with
[ADMISSION.md](ADMISSION.md) now and built after the first release.

---

## 8. Risks we are watching

| Risk | Signal | Response |
|---|---|---|
| Maintenance work crowds out the update path | Merged PRs since last release that serve none of §7's three categories | Phase rule in §7; reviewers defer, not merge |
| The demo app grows into a product | New end-user features on the messages surface | P4; reject |
| Hooks creep in under another name ("extension point", "registry", "override") | New indirection over an edit point | P3; reject unless it removes edits for every adopter |
| The position is claimed before it is true | README or docs promising easy updates before §6 targets are met | P7; remove the claim |
| Conventions decided after adopters exist | Any change to seed path, migration ids or release format after the first release | Settle all three before the first release |

---

*Changes to this document need the maintainer's approval (see
[ADMISSION.md §5](ADMISSION.md#5-what-needs-the-maintainer)). Everything else is decided by
applying it.*
