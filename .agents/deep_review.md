# Deep-review (static) workflow

Whole-repo static audit for bugs, design drift, and AI slop. Read-only: find, classify, file issues, STOP. Never fix in the same run — fixes go through the repo's issue workflow (executor ≠ verifier). Run from the repo root. No servers, no live traffic; the dynamic half lives in `.agents/dynamic_review.md`.

## Process lifecycle and cleanup (MANDATORY)

This workflow is static: do not start the application, a dev server, or a browser. If a quality gate or helper starts a process anyway, the agent owns it and MUST stop it before the final report.

Never finish a run with any process started by the agent still running. This includes background commands, test servers, watchers, and any browser process. Stop owned processes on success, failure, cancellation, timeout, and every early `STOP` path. A timeout is a safety net, not cleanup.

Prefer a foreground supervisor. If a long-lived command must run in the background, use a finite `timeout` budget and record its PID. Browser work follows `.agents/browser.md`: each script launches and closes its own chromium inside a `timeout`, so it leaves nothing running.

Use a task-appropriate cap for the application stack as well. On cleanup, send `SIGTERM` to the exact process or supervisor you started, wait for it, and use `SIGKILL` only if it is still alive. Check its children and the ports it owns. Never kill an unknown process or clear a port you did not open. Remove temporary PID/log/browser files. If cleanup cannot be verified, do not report the run as complete.

Scope: whole repo by default. Optional narrow scope: `--folder <path>`, `--file <a,b>`, or `--pr <n>` (checks out the PR branch and audits whole files touched by the diff, not just hunks).

## Project overrides (fill per repo; empty = generic)

```toml
# BACKEND = "apps/api/src"   # source root of the backend (discover below if unset)
# FRONTEND = "apps/web/src"  # source root of the frontend (discover below if unset)
# GATE = "make api-lint && make api-test && make web-build"  # quality gate command
# TRACKER = "gh issue create"  # how findings are filed
```

For this repo: backend `apps/api/src`, frontend `apps/web/src`, gate `make api-lint` + `make api-test` (+ `make web-build` for web), tracker `gh issue create` with labels `needs-human` (blocked), `enhancement` (deferred). Severity: **major** (bug, leak, arch violation — file an issue), **minor** (nit, follow-up — list in report unless cheap to file).

## Harness / model (defaults; override per run)

```toml
# HARNESS = "codex"   # codex | claude | opencode | pi — drives vigolium's audit leg
# MODEL = "gpt-5.6-terra"  # cheap alternative: gpt-5.6-luna
```

Say "run this with X" to switch harness (e.g. "run this with claude"). Codex is the only harness with a proven model-pin path (config swap, see dynamic doc step 2) — for others, wire the model per that harness's own config and verify via its session log; if the pin cannot be verified, record the actual model and move on.

Orchestration is allowed and expected: fan out one lens per subagent. Subagents are weaker — give each ONE task, the exact file paths (3–5 named files, not an area), the exact commands, the exact output shape (file:line + quote + 2-line trace, max 10 bullets), plus one line of known-context per file ruling out already-triaged claims. This doc is the orchestrator's; each subagent gets a slice, not the whole file.

## 0. Orient (read first)

A good repo documents all of this — read before discovering. Order matters: repo docs first (5 min), grep only for what the docs omit.

- `README.md` / `AGENTS.md` — stack, dev/seed commands, quality gate, tooling rules. If these name the backend/frontend roots, gate command, and seed creds, adopt them and skip the greps below.
- Architecture docs (`docs/ARCHITECTURE.md` or equivalent) + related `docs/`; structural map if present (`.codesight/wiki/`, else discover layout via `ls`).
- Dependency graph / blast-radius map if present (`.codesight/graph.md`) — note the high-impact files (most-imported modules, shared types, settings). Absent → derive from imports only for files you will touch.
- Seed script + credentials for later live checks (README first, else grep `seed` / `password` in backend source).
- Docs gap is itself a finding: if README/AGENTS omits dev/seed/gate commands or credentials (forcing grep discovery for any of them), file it as a minor docs issue. A repo that cannot onboard an agent in 5 minutes cannot onboard a human either.

## 1. Static sweep (always)

Run the repo gate first — a red gate is itself a major. Discover it from README/AGENTS (`make ...`, `npm run ...`, `pytest`, `ruff`, `tsc`); if the full suite times out in the sandbox (>300s), fall back to scoped files for touched areas and record the gate as unproven-not-green — a timeout is never a pass.

Then mechanical scans (paste counts into the report, not full output). Adapt extensions to the stack:

```bash
find <BACKEND> <FRONTEND> -name "*.py" -o -name "*.ts" -o -name "*.tsx" | xargs wc -l | sort -rn | head -20
grep -rn "TODO\|FIXME\|HACK\|XXX\|print(\|console\.log" <BACKEND> <FRONTEND> | head -30
grep -rn "password\|secret\|token\|api_key" <BACKEND> -i | grep -vi "test\|seed\|example" | head -20
```

Thresholds that trigger a finding, not a rule: file > 500 lines, function > 50 lines, same block 3+ copies, wrapper with a single call-site, abstraction with a single implementation.

## 2. The 9 lenses

Work file-by-file: take the top-10 from the step-1 size listing, intersect with high-impact files from step 0, then the rest. Every finding cites `file:line` + verbatim quote. No finding without a quote.

1. **Bugs** — wrong branch order, dropped errors, null/None misses, off-by-one, unawaited async, mutation of shared state, migration without rollback, unguarded check-then-act across `await`.
2. **Separation of concerns** — route handlers with business logic, services importing HTTP/web layers, integrations leaking into each other, frontend computing what the API should own. Compare against the architecture doc; divergence is a major.
3. **Async / event layer** — if the repo has one (event bus, job queue, webhooks): every event must flow publisher → bus → subscriber via the repo's wiring. Flag: direct calls duplicating an event path, `publish` with no subscriber, `subscribe` with no publisher, fan-out without the repo's fan-out flag, business logic inside bus adapters, silent exception swallowing in handlers. No event layer → skip.
4. **Hardcoded / non-agnostic** — tenant slugs, domains, emails, URLs, ports, provider names, claim URIs, magic numbers baked into logic. Must come from settings, env template, or provider/integration classes. Seed/demo values outside the seed script are majors.
5. **Data leaks** — PII/secrets in logs, error responses echoing internals, notification bodies over-sharing, audit trails missing on sensitive ops, seed credentials reachable outside dev, overly broad serializers on user objects.
6. **Engineering quality** — dead code, unreachable branches, unused params/imports, copy-paste siblings that should be one function, boolean-flag params, functions returning `None` on some paths and values on others, tests asserting implementation instead of behavior.
7. **AI slop** — speculative generality (config for one value, factory for one product, interface for one impl), comment restating the code, empty try/pass, placeholder text in UI, three near-identical components, dependency added for a few lines of stdlib. Subtract before adding: prove the abstraction has ≥2 callers or delete it. Reference: [https://github.com/petergyang/no-ai-slop](https://github.com/petergyang/no-ai-slop) (prose patterns, adapted to code).
8. **Contract drift** — frontend types vs API schemas: fields the UI reads that the API no longer sends, shapes the API sends that no type covers, `any` casts hiding drift, capability flags the UI ignores.
9. **Test gaps** — risk-bearing function (writes, auth, money/state transitions, migrations) with no test. Name the missing case, don't write it.

## 3. Verify before filing

For each candidate: `grep -n` the quote in the file, read the surrounding function, and check the other side of the claim (the subscriber for a publisher, the consumer for a filter, the peer for a pattern). Kill anything you cannot reproduce with a 2–3 line trace ("caller at A:L invokes B:L with X; guard at C:L rejects; no exit path").

## 4. File and report, STOP

1. One issue per major (title, `file:line` + quote, 2–3 line trace, why it matters). Reference related issues.
2. Post a summary report: majors filed (issue #s), minors listed, top 3 risks.
3. Append a usage report (report-only, never filed as an issue): own total tokens (from your session usage line) plus each subagent's usage line (tokens, tool uses, duration, model); for CLI tools that print token/cost figures, copy the figures verbatim; where a tool prints none, write "not reported" — never estimate. Shape:

```
Usage: self ~X tokens · subagent <task> ~Y tokens (model Z, Ns) · tool <name>: <verbatim or not reported>
```

4. STOP. Do not fix. Do not merge. Fixes happen in fresh sessions via the repo's issue workflow.

## Toolchain (why these)

- **repo gate** (lint, tests, typecheck — already in CI) — catches style, regressions, contract breaks for free.
- **pr-lens** (optional, architecture drift) — `npx skills add coldteadotai/pr-lens`, diagram the change and attach to the PR. Use when lenses 2/8 findings cluster: a picture of the drift beats paragraphs. https://github.com/coldteadotai/pr-lens
- **pstack principles** (lens 7 yardstick) — subtract-before-add, prove-it-works, test behavior not implementation. https://github.com/backnotprop/pstack
- **no-ai-slop** (lens 7 patterns) — 20+ slop patterns adapted to code. https://github.com/petergyang/no-ai-slop
- **zeroshot** (process model) — executor ≠ verifier, bounded repair, evidence-gated delivery. This file implements the verifier half. https://github.com/the-open-engine/zeroshot
- **openreview** (not adopted) — needs hosted bot infra; the repo's PR-review workflow already covers agent review without it. Revisit when PR volume justifies a bot. https://github.com/vercel-labs/openreview
