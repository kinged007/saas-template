# Webhooks

> **Navigation aid.** Route list and file locations extracted via AST. Read the source files listed below before implementing or modifying this subsystem.

The Webhooks subsystem handles **10 routes** and touches: db.

## Routes

- `GET` `/events` [webhook]
  `apps/api/src/api/routes/webhooks.py`
- `GET` `/subscriptions` [db, webhook]
  `apps/api/src/api/routes/webhooks.py`
- `POST` `/subscriptions` → in: WebhookSubscriptionCreate [webhook]
  `apps/api/src/api/routes/webhooks.py`
- `PATCH` `/subscriptions/{subscription_id}` params(subscription_id) [webhook]
  `apps/api/src/api/routes/webhooks.py`
- `DELETE` `/subscriptions/{subscription_id}` params(subscription_id) [db, webhook]
  `apps/api/src/api/routes/webhooks.py`
- `POST` `/subscriptions/{subscription_id}/rotate-secret` params(subscription_id) → in: WebhookSubscriptionCreate [webhook]
  `apps/api/src/api/routes/webhooks.py`
- `GET` `/deliveries` [db, webhook]
  `apps/api/src/api/routes/webhooks.py`
- `GET` `/subscriptions/{subscription_id}/deliveries` params(subscription_id) [db, webhook]
  `apps/api/src/api/routes/webhooks.py`
- `GET` `/deliveries/{delivery_id}` params(delivery_id) [webhook]
  `apps/api/src/api/routes/webhooks.py`
- `POST` `/deliveries/{delivery_id}/redeliver` params(delivery_id) → in: WebhookSubscriptionCreate [webhook]
  `apps/api/src/api/routes/webhooks.py`

## Source Files

Read these before implementing or modifying this subsystem:
- `apps/api/src/api/routes/webhooks.py`

---
_Back to [overview.md](./overview.md)_