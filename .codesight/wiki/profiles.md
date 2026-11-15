# Profiles

> **Navigation aid.** Route list and file locations extracted via AST. Read the source files listed below before implementing or modifying this subsystem.

The Profiles subsystem handles **15 routes** and touches: db, auth.

## Routes

- `GET` `/me/profile` → in: Use, out: list
  `apps/api/src/api/routes/profiles.py`
- `PUT` `/me/profile` → in: ProfileUpdate, out: list [db]
  `apps/api/src/api/routes/profiles.py`
- `PATCH` `/me/profile` → in: ProfileUpdate, out: list [db]
  `apps/api/src/api/routes/profiles.py`
- `GET` `/users/{user_id}/profile` params(user_id) → in: Use, out: list [auth]
  `apps/api/src/api/routes/profiles.py`
- `PATCH` `/users/{user_id}/profile` params(user_id) → in: ProfileUpdate, out: list [auth, db]
  `apps/api/src/api/routes/profiles.py`
- `PUT` `/users/{user_id}/profile` params(user_id) → in: ProfileUpdate, out: list [auth, db]
  `apps/api/src/api/routes/profiles.py`
- `GET` `/users/{user_id}/notification-preferences` params(user_id) → in: Use, out: list
  `apps/api/src/api/routes/profiles.py`
- `PUT` `/users/{user_id}/notification-preferences` params(user_id) → in: ProfileUpdate, out: list
  `apps/api/src/api/routes/profiles.py`
- `GET` `/users/{user_id}/sessions` params(user_id) → in: Use, out: list [auth]
  `apps/api/src/api/routes/profiles.py`
- `DELETE` `/users/{user_id}/sessions` params(user_id) → out: list [auth, db]
  `apps/api/src/api/routes/profiles.py`
- `DELETE` `/users/{user_id}/sessions/{session_id}` params(user_id, session_id) → out: list [auth, db]
  `apps/api/src/api/routes/profiles.py`
- `GET` `/me/export` → in: Use, out: list
  `apps/api/src/api/routes/profiles.py`
- `GET` `/users/{user_id}/export` params(user_id) → in: Use, out: list
  `apps/api/src/api/routes/profiles.py`
- `DELETE` `/me` → out: list [db]
  `apps/api/src/api/routes/profiles.py`
- `DELETE` `/users/{user_id}` params(user_id) → out: list [db]
  `apps/api/src/api/routes/profiles.py`

## Source Files

Read these before implementing or modifying this subsystem:
- `apps/api/src/api/routes/profiles.py`

---
_Back to [overview.md](./overview.md)_