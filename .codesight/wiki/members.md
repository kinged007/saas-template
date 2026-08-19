# Members

> **Navigation aid.** Route list and file locations extracted via AST. Read the source files listed below before implementing or modifying this subsystem.

The Members subsystem handles **2 routes** and touches: db.

## Routes

- `PATCH` `/{membership_id}` params(membership_id)
  `apps/api/src/api/routes/members.py`
- `DELETE` `/{membership_id}` params(membership_id) [db]
  `apps/api/src/api/routes/members.py`

## Source Files

Read these before implementing or modifying this subsystem:
- `apps/api/src/api/routes/members.py`

---
_Back to [overview.md](./overview.md)_