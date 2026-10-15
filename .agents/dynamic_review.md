# Dynamic-review workflow

Live security audit against a running stack. Read-only: scan, triage, file issues, STOP. Never fix in the same run — fixes go through the repo's issue workflow (executor ≠ verifier). Run from the repo root. The static half lives in `.agents/deep_review.md`; run it first so scanner hits land on already-reviewed code.

Scope: whole API by default. Optional narrow scope: `--folder <path>` or `--file <a,b>` (live-scan only the routes those files own).

## Project overrides (fill per repo; empty = generic)

```toml
# BACKEND = "apps/api/src"
# FRONTEND = "apps/web/src"
# DEV = "python3 scripts/dev.py"   # foreground supervisor that stops its servers on exit
# API_PORT = "8000"
# WEB_PORT = "5173"
# HEALTH = "/api/v1/readyz"        # health path under the API root
# SPEC = "/openapi.json"           # machine-readable API spec path
# LOGIN = "/api/v1/auth/login"     # email+password login endpoint (for the auth pass)
# SEED_USER = "admin@tenantflex.dev"
# SEED_PASSWORD = "Tenantflex1!"
# TRACKER = "gh issue create"
```

For this repo: backend `apps/api/src`, frontend `apps/web/src`, dev `scripts/dev.py` (ports 8000/5173), health `/api/v1/readyz`, spec `/openapi.json`, login `/api/v1/auth/login`, seed `admin@tenantflex.dev` / `Tenantflex1!`, tracker `gh issue create` with label `needs-human` (blocked). Every confirmed hit is a major — file an issue per hit.

## Harness / model (defaults; override per run)

```toml
# HARNESS = "codex"   # codex | claude | opencode | pi — drives vigolium's audit leg
# MODEL = "gpt-5.6-terra"  # cheap alternative: gpt-5.6-luna
```

Say "run this with X" to switch harness (e.g. "run this with claude"). Codex is the only harness with a proven model-pin path (config swap below) — for others, wire the model per that harness's own config and verify via its session log; if the pin cannot be verified, record the actual model and move on.

Orchestration is allowed and expected: fan out per-area agents (static lenses, one lens per agent; dynamic scans, one target per agent). Subagents are weaker — give each ONE task, the exact file paths (3–5 named files, not an area), the exact commands, the exact output shape (file:line + quote + 2-line trace, max 10 bullets), plus one line of known-context per file that rules out already-triaged claims. This doc is the orchestrator's; each subagent gets a slice, not the whole file.

## 0. Orient (read first)

A good repo documents all of this — read before discovering. Order matters: repo docs first (5 min), grep only for what the docs omit.

- `.agents/deep_review.md` step 0 (same orientation files).
- Dev/seed commands + credentials: README/AGENTS first, seed script second, grep last (`seed` / `password` in backend source). If the docs name them, adopt and move on. Record the login email + password here before proceeding — the authenticated pass (step 3) needs them.

## Process lifecycle and cleanup (MANDATORY)

Never finish a run with a process started by the agent still running. This includes the API/frontend stack, supervisors, watchers, and test servers. Stop every owned process on success, failure, cancellation, timeout, and every early `STOP` path. A timeout is only a safety net, not cleanup.

Run long-lived commands in the foreground when possible. If backgrounding is necessary, give the command a finite budget and record its PID. For this repo, use `python3 scripts/dev.py` directly after setup rather than backgrounding `make dev`; the supervisor handles `SIGINT` and `SIGTERM` and kills its child process groups.

Use a task-appropriate cap for every background service.

Browser automation is not a background service: per `.agents/browser.md`, each script launches and closes its own chromium inside a `timeout`, so it leaves nothing behind.

At every exit path, stop every process started in this run, including the stack supervisor. Send `SIGTERM` to the exact process you started, wait for it, and use `SIGKILL` only if it remains alive. Check its children and the ports it owns. Never kill an unknown process or clear a port you did not open. Remove temporary PID/log/browser files. If cleanup cannot be verified, do not report the run as complete.

## 1. Own the stack

One stack, yours, on the reviewed commit. Before starting, check that the API and web ports are free. If either is occupied by a process you did not start, STOP and report it; never kill an unknown process.

Use the repo's foreground supervisor. For this repo, invoke `python3 scripts/dev.py` directly after setup instead of backgrounding `make dev`; the supervisor handles `SIGINT` and `SIGTERM` and kills both child process groups. If the workflow must continue while the stack runs, put the supervisor under a finite budget and keep its PID:

```bash
git status -sb  # must be clean — the scan is only valid on committed code
if ss -tln 2>/dev/null | grep -qE ":($API_PORT|$WEB_PORT)([[:space:]]|$)"; then
  echo "API/web port already in use; refusing to start another stack" >&2
  exit 1
fi
runtime_dir=$(mktemp -d /tmp/dynamic-review.XXXXXX)
nohup timeout --signal=TERM --kill-after=15s 2h <DEV> >"$runtime_dir/dev.log" 2>&1 &
DEV_PID=$!
echo "$DEV_PID" >"$runtime_dir/dev.pid"
sleep 25 && check <HEALTH> returns 2xx  # find the health endpoint first (grep healthz/readyz/health in backend routes); a bare / is usually NOT it
```

Keep `DEV_PID` and `runtime_dir`; do not lose them. Verify the stack serves the reviewed tree: `git rev-parse --short HEAD` matches the checkout the server started from (same shell, same `git status -sb` as above — if you pulled or switched branches after starting, restart). If a port re-binds right after your kill, stop and ask — another live session may own it.

If browser verification is required, use Playwright per `.agents/browser.md` against the running stack. Follow that file's setup step to locate the frontend app, then run each script from there inside a `timeout`; it launches and closes its own chromium, so there is no browser process to stop at exit.

Use a task-appropriate cap for the application stack as well. At every exit path, stop every process started in this run, including the stack supervisor. Send `SIGTERM` to the exact process you started, wait for it, and use `SIGKILL` only if it remains alive. Check its children and the ports it owns. Never kill an unknown process or clear a port you did not open. Remove temporary PID/log/browser files. If cleanup cannot be verified, do not report the run as complete.

## 2. Install vigolium (once per machine)

```bash
which vigolium || curl -fsSL https://vigolium.com/install.sh | bash  # or: npm install -g @vigolium/vigolium
```

Model routing: there is NO `--model` flag on `vigolium agent audit`. The audit leg shells out to the harness CLI, which reads its model from its own config. Proven for codex: `model` in `~/.codex/config.toml` (default `gpt-5.6-terra`; cheap `gpt-5.6-luna`). `CODEX_MODEL` env was tested and is IGNORED. To pin luna for one run, temporarily swap the config value and restore it in a `finally` (prove restoration with grep after):

```bash
sed -i 's/model = "gpt-5.6-terra"/model = "gpt-5.6-luna"/' ~/.codex/config.toml
vigolium agent audit --source <BACKEND> --driver audit --agent $HARNESS --mode lite -S --output-dir /tmp/vig-api --clean-raw
sed -i 's/model = "gpt-5.6-luna"/model = "gpt-5.6-terra"/' ~/.codex/config.toml; grep -n '^model = ' ~/.codex/config.toml
```

Verify the pin held via the harness session log (for codex: `~/.codex/sessions/<date>/rollout-*.jsonl`) — the harness's own role tables may name other models, so role-table hits do NOT prove the runner model; find the runner/collaboration field. If the pin did not hold, record the actual model and move on.

Verify the harness CLI exists first (`codex --version`, `claude --version`, …); if missing, STOP and label needs-human. First run is always `--mode lite`: it validates the whole pipeline (install → auth → model → results) in ~3 min before spending 40–50 min on deep/balanced.

## 3. Scan

Source audit (no server needed, but run it here so static + dynamic land in one report). Always `--mode lite` first (pipeline check, ~3 min), then escalate to deep/balanced:

```bash
vigolium agent audit --source <BACKEND> --driver audit --agent $HARNESS --mode deep -S --output-dir /tmp/vig-api --clean-raw
vigolium agent audit --source <FRONTEND> --driver audit --agent $HARNESS --mode balanced -S --output-dir /tmp/vig-web --clean-raw
```

`-S` keeps the main DB untouched; `--clean-raw` removes `vigolium-results/` from the source tree after the run (else it pollutes `git status`). If the harness leg fails with "model at capacity", wait and retry once — it is transient, not auth.

Record vigolium's reported token/cost figures in the report (step 5) — running total per run, so we can compare models later.

Live scan (needs the step-1 stack). Save the spec to a file first — `-T <url>` is unverified, `-T <file>` works:

```bash
python3 -c "import urllib.request as u; open('/tmp/openapi.json','wb').write(u.urlopen('http://localhost:$API_PORT/<SPEC>', timeout=15).read())"
# unauthenticated pass (front door only):
vigolium scan -T /tmp/openapi.json -I openapi -t http://localhost:$API_PORT --strategy lite --intensity quick --scanning-max-duration 12m
```

Authenticated pass (the remaining routes — without this only the front door is tested). Obtain the session yourself from the seeded creds (step 0); shape below is email+password JSON, adapt to the repo's login contract:

```bash
python3 -c "import urllib.request, json; r = urllib.request.urlopen(urllib.request.Request('http://localhost:$API_PORT/<LOGIN>', data=json.dumps({'email':'<SEED_USER>','password':'<SEED_PASSWORD>'}).encode(), headers={'Content-Type':'application/json'})); open('/tmp/auth.json','w').write(r.read().decode())"
```

then pass the access token as `Authorization: Bearer <token>` via `--spec-header` and the refresh cookie via `--auth-file` (see `vigolium scan --help`). If auth-harness flags fail, run unauthenticated, record it as a coverage gap, and file a follow-up issue — do not fake it.

## 3b. AI-slop sweep (no-ai-slop patterns)

After triage, run one pass over scanner-touched files for agent-generated cruft: speculative generality (config for one value, factory for one product, interface for one impl), comments restating the code, empty try/pass, placeholder UI text, three near-identical components, dependency added for stdlib work. Reference: https://github.com/petergyang/no-ai-slop (prose patterns, adapted to code). File slop as minor unless it hides a bug.

## 4. Triage every hit, then STOP the stack

For each hit: reproduce against the code with a 2–3 line trace ("request to A:L reaches B:L with X; guard at C:L missing; exploit is ..."). Drop anything unreproducible — scanner output is a lead, never a finding by itself. Record kept/dropped with one-line reasons.

Then stop your stack (same one you started — kill the supervisor process, confirm ports free with `ss -tln | grep -E ":($API_PORT|$WEB_PORT)"` showing nothing) and verify:

```bash
git status -sb  # must be clean — `vigolium-results/` removed (--clean-raw), scan artifacts never committed
```

## 5. File and report, STOP

1. One issue per confirmed hit (title, endpoint + `file:line` + quote, 2–3 line trace, why it matters).
2. Post a summary report: issues filed (#s), hits triaged (kept/dropped with reasons), top 3 risks.
3. Append a usage report (report-only, never filed as an issue): own total tokens (from your session usage line) plus each subagent's usage line (tokens, tool uses, duration, model); for CLI tools that print token/cost figures, copy the figures verbatim; where a tool prints none, write "not reported" — never estimate. Shape:

```
Usage: self ~X tokens · subagent <task> ~Y tokens (model Z, Ns) · tool <name>: <verbatim or not reported>
```
4. STOP. Do not fix. Do not merge.
