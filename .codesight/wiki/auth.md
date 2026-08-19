# Auth

> **Navigation aid.** Route list and file locations extracted via AST. Read the source files listed below before implementing or modifying this subsystem.

The Auth subsystem handles **5 routes** and touches: auth.

## Routes

- `POST` `/register` → in: RegisterRequest, out: TokenResponse [auth]
  `apps/api/src/api/routes/auth.py`
- `POST` `/login` → in: RegisterRequest, out: TokenResponse [auth]
  `apps/api/src/api/routes/auth.py`
- `POST` `/refresh` → in: RegisterRequest, out: TokenResponse [auth]
  `apps/api/src/api/routes/auth.py`
- `POST` `/logout` → in: RegisterRequest, out: TokenResponse [auth]
  `apps/api/src/api/routes/auth.py`
- `GET` `/me` → out: TokenResponse
  `apps/api/src/api/routes/auth.py`

## Middleware

- **auth** (auth) — `apps/api/src/services/auth.py`
- **authProvider** (auth) — `apps/web/src/providers/authProvider.ts`

## Source Files

Read these before implementing or modifying this subsystem:
- `apps/api/src/api/routes/auth.py`

---
_Back to [overview.md](./overview.md)_