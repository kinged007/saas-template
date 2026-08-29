# Profiles

> **Navigation aid.** Route list and file locations extracted via AST. Read the source files listed below before implementing or modifying this subsystem.

The Profiles subsystem handles **8 routes** and touches: db.

## Routes

- `GET` `/me/profile` → in: Use
  `apps/api/src/api/routes/profiles.py`
- `PUT` `/me/profile` → in: ProfileUpdate [db]
  `apps/api/src/api/routes/profiles.py`
- `PATCH` `/me/profile` → in: ProfileUpdate [db]
  `apps/api/src/api/routes/profiles.py`
- `GET` `/users/{user_id}/profile` params(user_id) → in: Use
  `apps/api/src/api/routes/profiles.py`
- `GET` `/me/export` → in: Use
  `apps/api/src/api/routes/profiles.py`
- `GET` `/users/{user_id}/export` params(user_id) → in: Use
  `apps/api/src/api/routes/profiles.py`
- `DELETE` `/me` → in: DeleteMeRequest [db]
  `apps/api/src/api/routes/profiles.py`
- `DELETE` `/users/{user_id}` params(user_id) → in: DeleteMeRequest [db]
  `apps/api/src/api/routes/profiles.py`

## Source Files

Read these before implementing or modifying this subsystem:
- `apps/api/src/api/routes/profiles.py`

---
_Back to [overview.md](./overview.md)_