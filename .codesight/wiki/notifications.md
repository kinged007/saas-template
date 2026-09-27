# Notifications

> **Navigation aid.** Route list and file locations extracted via AST. Read the source files listed below before implementing or modifying this subsystem.

The Notifications subsystem handles **6 routes** and touches: auth, db.

## Routes

- `GET` `/preferences`
  `apps/api/src/api/routes/notifications.py`
- `PUT` `/preferences` → in: NotificationPreferencesUpdate
  `apps/api/src/api/routes/notifications.py`
- `GET` `/unsubscribe` [auth]
  `apps/api/src/api/routes/notifications.py`
- `PATCH` `/read-all`
  `apps/api/src/api/routes/notifications.py`
- `PATCH` `/{notification_id}` params(notification_id) [db]
  `apps/api/src/api/routes/notifications.py`
- `DELETE` `/{notification_id}` params(notification_id) [db]
  `apps/api/src/api/routes/notifications.py`

## Source Files

Read these before implementing or modifying this subsystem:
- `apps/api/src/api/routes/notifications.py`

---
_Back to [overview.md](./overview.md)_