# Api_keys

> **Navigation aid.** Route list and file locations extracted via AST. Read the source files listed below before implementing or modifying this subsystem.

The Api_keys subsystem handles **5 routes** and touches: db.

## Routes

- `GET` ``
  `apps/api/src/api/routes/api_keys.py`
- `GET` `/effective-permissions`
  `apps/api/src/api/routes/api_keys.py`
- `POST` `` → in: ApiKeyCreate
  `apps/api/src/api/routes/api_keys.py`
- `PATCH` `/{api_key_id}` params(api_key_id)
  `apps/api/src/api/routes/api_keys.py`
- `DELETE` `/{api_key_id}` params(api_key_id) [db]
  `apps/api/src/api/routes/api_keys.py`

## Source Files

Read these before implementing or modifying this subsystem:
- `apps/api/src/api/routes/api_keys.py`

---
_Back to [overview.md](./overview.md)_