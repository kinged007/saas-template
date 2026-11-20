# Workspaces

> **Navigation aid.** Route list and file locations extracted via AST. Read the source files listed below before implementing or modifying this subsystem.

The Workspaces subsystem handles **8 routes** and touches: db.

## Routes

- `GET` `/search` → out: list
  `apps/api/src/api/routes/workspaces.py`
- `GET` `/export/resources` → out: list
  `apps/api/src/api/routes/workspaces.py`
- `GET` `/export` → out: list
  `apps/api/src/api/routes/workspaces.py`
- `GET` `/{workspace_id}` params(workspace_id) → out: list
  `apps/api/src/api/routes/workspaces.py`
- `PATCH` `/{workspace_id}` params(workspace_id) → out: list
  `apps/api/src/api/routes/workspaces.py`
- `POST` `/{workspace_id}/transfer` params(workspace_id) → in: WorkspaceCreate, out: list
  `apps/api/src/api/routes/workspaces.py`
- `DELETE` `/{workspace_id}` params(workspace_id) → out: list [db]
  `apps/api/src/api/routes/workspaces.py`
- `DELETE` `/{workspace_id}/membership` params(workspace_id) → out: list [db]
  `apps/api/src/api/routes/workspaces.py`

## Source Files

Read these before implementing or modifying this subsystem:
- `apps/api/src/api/routes/workspaces.py`

---
_Back to [overview.md](./overview.md)_