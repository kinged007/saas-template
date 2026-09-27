# Oauth

> **Navigation aid.** Route list and file locations extracted via AST. Read the source files listed below before implementing or modifying this subsystem.

The Oauth subsystem handles **2 routes** and touches: auth, cache.

## Routes

- `GET` `/{provider_id}/authorize` params(provider_id) [auth, cache]
  `apps/api/src/api/routes/oauth.py`
- `GET` `/{provider_id}/callback` params(provider_id) [auth, cache]
  `apps/api/src/api/routes/oauth.py`

## Source Files

Read these before implementing or modifying this subsystem:
- `apps/api/src/api/routes/oauth.py`

---
_Back to [overview.md](./overview.md)_