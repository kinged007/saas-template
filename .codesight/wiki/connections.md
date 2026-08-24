# Connections

> **Navigation aid.** Route list and file locations extracted via AST. Read the source files listed below before implementing or modifying this subsystem.

The Connections subsystem handles **6 routes** and touches: db.

## Routes

- `GET` `/providers`
  `apps/api/src/api/routes/connections.py`
- `GET` `` [db]
  `apps/api/src/api/routes/connections.py`
- `POST` `` → in: ConnectionCreate
  `apps/api/src/api/routes/connections.py`
- `PATCH` `/{connection_id}` params(connection_id) [db]
  `apps/api/src/api/routes/connections.py`
- `DELETE` `/{connection_id}` params(connection_id) [db]
  `apps/api/src/api/routes/connections.py`
- `POST` `/{connection_id}/test` params(connection_id) → in: ConnectionCreate
  `apps/api/src/api/routes/connections.py`

## Source Files

Read these before implementing or modifying this subsystem:
- `apps/api/src/api/routes/connections.py`

---
_Back to [overview.md](./overview.md)_