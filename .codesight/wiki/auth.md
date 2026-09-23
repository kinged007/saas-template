# Auth

> **Navigation aid.** Route list and file locations extracted via AST. Read the source files listed below before implementing or modifying this subsystem.

The Auth subsystem handles **20 routes** and touches: auth, email, db, cache.

## Routes

- `GET` `/config` → out: TokenResponse [auth]
  `apps/api/src/api/routes/auth.py`
- `POST` `/register` → in: RegisterRequest, out: TokenResponse [auth]
  `apps/api/src/api/routes/auth.py`
- `POST` `/forgot-password` → in: RegisterRequest, out: TokenResponse [auth]
  `apps/api/src/api/routes/auth.py`
- `POST` `/reset-password` → in: RegisterRequest, out: TokenResponse [auth]
  `apps/api/src/api/routes/auth.py`
- `POST` `/verify-email` → in: RegisterRequest, out: TokenResponse [auth]
  `apps/api/src/api/routes/auth.py`
- `POST` `/resend-verification` → in: RegisterRequest, out: TokenResponse [auth, email]
  `apps/api/src/api/routes/auth.py`
- `POST` `/login` → in: RegisterRequest, out: TokenResponse [auth]
  `apps/api/src/api/routes/auth.py`
- `POST` `/refresh` → in: RegisterRequest, out: TokenResponse [auth]
  `apps/api/src/api/routes/auth.py`
- `GET` `/2fa/status` → out: TokenResponse
  `apps/api/src/api/routes/auth.py`
- `POST` `/2fa/setup` → in: RegisterRequest, out: TokenResponse
  `apps/api/src/api/routes/auth.py`
- `POST` `/2fa/enable` → in: RegisterRequest, out: TokenResponse
  `apps/api/src/api/routes/auth.py`
- `POST` `/2fa/disable` → in: RegisterRequest, out: TokenResponse [auth]
  `apps/api/src/api/routes/auth.py`
- `POST` `/2fa/backup-codes` → in: RegisterRequest, out: TokenResponse [auth]
  `apps/api/src/api/routes/auth.py`
- `POST` `/2fa/login` → in: RegisterRequest, out: TokenResponse [auth]
  `apps/api/src/api/routes/auth.py`
- `GET` `/sessions` → out: TokenResponse [auth]
  `apps/api/src/api/routes/auth.py`
- `DELETE` `/sessions` → out: TokenResponse [auth, db]
  `apps/api/src/api/routes/auth.py`
- `POST` `/logout` → in: RegisterRequest, out: TokenResponse [auth]
  `apps/api/src/api/routes/auth.py`
- `DELETE` `/sessions/{session_id}` params(session_id) → out: TokenResponse [auth, db]
  `apps/api/src/api/routes/auth.py`
- `GET` `/me` → out: TokenResponse
  `apps/api/src/api/routes/auth.py`
- `POST` `/token` → in: OAuthTokenRequest [auth, db, cache]
  `apps/api/src/api/routes/oauth.py`

## Middleware

- **ratelimit** (auth) — `apps/api/src/core/security/ratelimit.py`
- **auth** (auth) — `apps/api/src/services/auth.py`
- **authProvider** (auth) — `apps/web/src/providers/authProvider.ts`

## Source Files

Read these before implementing or modifying this subsystem:
- `apps/api/src/api/routes/auth.py`
- `apps/api/src/api/routes/oauth.py`

---
_Back to [overview.md](./overview.md)_