# Admin

> **Navigation aid.** Route list and file locations extracted via AST. Read the source files listed below before implementing or modifying this subsystem.

The Admin subsystem handles **6 routes** and touches: db.

## Routes

- `GET` `/users` [db]
  `apps/api/src/api/routes/admin.py`
- `GET` `/users/{user_id}` params(user_id) [db]
  `apps/api/src/api/routes/admin.py`
- `PATCH` `/users/{user_id}` params(user_id)
  `apps/api/src/api/routes/admin.py`
- `GET` `/workspaces` [db]
  `apps/api/src/api/routes/admin.py`
- `PATCH` `/workspaces/{workspace_id}/flags` params(workspace_id)
  `apps/api/src/api/routes/admin.py`
- `GET` `/audit` [db]
  `apps/api/src/api/routes/admin.py`

## Source Files

Read these before implementing or modifying this subsystem:
- `apps/api/src/api/routes/admin.py`

---
_Back to [overview.md](./overview.md)_