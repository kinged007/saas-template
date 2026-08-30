# Workspace_settings

> **Navigation aid.** Route list and file locations extracted via AST. Read the source files listed below before implementing or modifying this subsystem.

The Workspace_settings subsystem handles **3 routes** and touches: db.

## Routes

- `GET` `/{key}` params(key) → in: st
  `apps/api/src/api/routes/workspace_settings.py`
- `PUT` `/{key}` params(key)
  `apps/api/src/api/routes/workspace_settings.py`
- `DELETE` `/{key}` params(key) [db]
  `apps/api/src/api/routes/workspace_settings.py`

## Related Models

- **Workspace** (5 fields) → [database.md](./database.md)

## Source Files

Read these before implementing or modifying this subsystem:
- `apps/api/src/api/routes/workspace_settings.py`

---
_Back to [overview.md](./overview.md)_