# Outbound webhooks

Subscribe a workspace to domain events over HTTP. Each matching event fans
out into one `WebhookDelivery` per subscription; deliveries retry with
backoff until success or exhaustion, and the log is visible in the UI.

## Quick start

1. `POST /api/v1/webhooks/subscriptions` with `{url, events}` — the response
   includes the signing `secret` **once** (store it, it is never shown again).
2. Verify each delivery (below) and return any 2xx.
3. Watch the delivery log in the webhooks page; retry failed rows with
   `POST /api/v1/webhooks/deliveries/{id}/redeliver`.

`GET /api/v1/webhooks/events` lists subscribable event names
(`workspace.created`, `invitation.created`, `member.invited`,
`member.joined`, `member.role_changed`, `member.removed`,
`apikey.created`, `apikey.revoked`, `audit.entry.created`,
`conversation.message.created`). An empty `events` list means all events.

## Delivery format

`POST {url}` with `Content-Type: application/json` and headers:

| Header | Value |
| --- | --- |
| `X-Webhook-Event` | public event name, e.g. `member.joined` |
| `X-Webhook-Delivery` | delivery id — dedupe key (retries reuse it) |
| `X-Webhook-Timestamp` | ISO-8601 send time |
| `X-Webhook-Signature` | `sha256=<hex>` HMAC (below) |

Body envelope:

```json
{
  "event": "member.joined",
  "event_id": "01J…",
  "occurred_at": "2026-09-14T12:00:00+00:00",
  "workspace_id": "3fa…",
  "data": { "workspace_id": "3fa…", "user_id": "9c2…", "...": "original event payload" }
}
```

Delivery is **at-least-once and unordered** across retries — dedupe on
`X-Webhook-Delivery` / `event_id` before acting on the payload.

## Verifying signatures

`signature = "sha256:" + hex(HMAC_SHA256(secret, timestamp + "." + raw_body))`
where `timestamp` is the `X-Webhook-Timestamp` value verbatim and `raw_body`
is the exact request bytes. Compare with a constant-time equality check.

```python
import hashlib, hmac

def verify(secret: str, timestamp: str, raw_body: bytes, signature: str) -> bool:
    expected = "sha256=" + hmac.new(
        secret.encode(), timestamp.encode() + b"." + raw_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)
```

Timestamps are send times, not nonces — accept normal clock skew between the
header and your server clock when enforcing freshness.

## Retries

Any 2xx is success. Anything else (non-2xx, timeout after 10s, connection
error) retries with backoff after attempt N of 1m, 5m, 30m, 2h, 12h; the 6th
attempt is the last and a failure there marks the delivery `exhausted`.
Failed attempts record `response_status` / `error` on the delivery row.
`POST …/deliveries/{id}/redeliver` resets a failed/exhausted delivery to
`pending` (with a best-effort immediate attempt).

`POST …/subscriptions/{id}/rotate-secret` returns a replacement secret;
deliveries already in flight keep the old signature, new attempts use the new
one, so rotate during a quiet window or tolerate one overlap.

## Limits

- HTTPS required in production; loopback/private targets are rejected
  (SSRF guard). Payloads over 256 KiB fail the attempt without sending.
- Subscriptions are workspace-scoped (`X-Workspace-ID`); cross-workspace ids
  return 404 so callers cannot probe other workspaces.
- Permissions: `webhook:read` (list subscriptions/deliveries),
  `webhook:manage` (create/update/delete, rotate, redeliver) — both held by
  the `admin` role (owners hold `*`).
