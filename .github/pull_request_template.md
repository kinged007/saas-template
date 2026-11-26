## What and why

<!-- One or two sentences. Link the issue. -->

## Release-note line

<!-- The one line an adopter reads to decide whether to take this change.
     Include any renames as old/path → new/path, and anything they must do. -->

Area: api
Release-note: <one line an adopter reads to decide whether to take this change>

<!-- Area is one of api / web / db / infra. If more, say why it can't be split. -->

## Admission ([docs/product/ADMISSION.md](https://github.com/kinged007/saas-template/blob/main/docs/product/ADMISSION.md))

**Gate 0 — milestone** (one of):
- [ ] in a started milestone · [ ] security fix · [ ] restores documented behaviour

**Gate 1 — scope** (plumbing, not a domain feature; no demo-surface growth):
- [ ] Plumbing every multi-tenant B2B SaaS needs (ADMISSION Gate 1 list)
- [ ] Not a domain feature (orders, invoices, projects, CRM, chat…)
- [ ] Does not grow the demo surface beyond exercising plumbing

**Gate 2 — update safety**
- [ ] Renames / moves / deletions under `apps/` are listed in the release-note line
- [ ] New migrations use timestamp ids (DECISIONS D-04)
- [ ] Edit points not enlarged, split, moved or renamed — or their docs updated here
- [ ] Security fix is not bundled with anything else
- [ ] Workspace-scoped authorisation is enforced on the server

**Gate 3 — shape**
- [ ] No new hook / plugin / override layer (or: it removes an edit point for every adopter — explain)
- [ ] Optional capability is off by default or removable in one sitting

**Gate 4 — quality**
- [ ] Failures are loud and specific
- [ ] Tests state observable behaviour
- [ ] Docs touched are true against this diff
- [ ] Unbranded — no credits, banners or marketing copy

**Verdict line:** <!-- e.g. "Accept — Gate 0 security fix; Gates 1–4 pass." -->
