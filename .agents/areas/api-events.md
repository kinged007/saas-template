# api-events

Paths: `apps/api/src/events/**`, `jobs/**`, `workflows/**`, `realtime/**`, `email/**`, `apps/api/src/services/webhooks.py`, `webhook_dispatcher.py`, `jobs.py`, `notifications.py`, `apps/api/src/models/{webhook,jobs}.py` (shared with api-domain), `docs/WEBHOOKS.md`.

Purpose: domain event bus (in-process or NATS), subscriber workflows, scheduled jobs, outbound webhooks, WebSocket push, outgoing email.

Entry points:
- `src/events/factory.py`: `build_event_bus`; drivers named in `events/subjects.py`.
- `src/events/publisher.py`: `publish_event`, `publish_audit`.
- `src/workflows/__init__.py`: `build_workflows`, the subject-to-handler table.
- `src/jobs/__init__.py`: job registry contract; `scheduler.py`, `executor.py`, `builtin.py`.
- `src/services/webhooks.py`: `dispatch_due`; loop in `webhook_dispatcher.py`.
- `src/realtime/manager.py`: per-user WebSocket sessions; route in `src/api/routes/ws.py`.
- `src/email/factory.py`: `build_email_sender` (console and SMTP senders).

Conventions:
- Services call `publish_event` / `publish_audit`; they do not build envelopes or subject strings.
- Workflows open their own DB session per event.
- Webhook deliveries are retried with backoff until success or `exhausted` (`docs/WEBHOOKS.md`).

Pitfalls:
- Workflows and the dispatch loop may run in several replicas; claims must stay atomic.
- Registering a workflow requires an edit in `workflows/__init__.py`.

Checks:
- `cd apps/api && uv run pytest -q --tb=short -p no:cacheprovider`
- `make api-test-nats` (needs docker; `make nats-up`)
- `cd apps/api && uv run ruff check . && uv run ruff format --check .`
