# Auth

> **Navigation aid.** Route list and file locations extracted via AST. Read the source files listed below before implementing or modifying this subsystem.

The Auth subsystem handles **22 routes** and touches: auth, email, db, cache.

## Routes

- `GET` `/config` → in: Use, out: TokenResponse [auth]
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
- `POST` `/change-password` → in: RegisterRequest, out: TokenResponse [auth]
  `apps/api/src/api/routes/auth.py`
- `GET` `/2fa/status` → in: Use, out: TokenResponse
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
- `GET` `/sessions` → in: Use, out: TokenResponse [auth]
  `apps/api/src/api/routes/auth.py`
- `DELETE` `/sessions` → out: TokenResponse [auth, db]
  `apps/api/src/api/routes/auth.py`
- `POST` `/logout` → in: RegisterRequest, out: TokenResponse [auth]
  `apps/api/src/api/routes/auth.py`
- `DELETE` `/sessions/{session_id}` params(session_id) → out: TokenResponse [auth, db]
  `apps/api/src/api/routes/auth.py`
- `GET` `/me` → in: Use, out: TokenResponse [auth]
  `apps/api/src/api/routes/auth.py`
- `POST` `/token` → in: OAuthTokenRequest [auth, db, cache]
  `apps/api/src/api/routes/oauth.py`
- `POST` `/users/{user_id}/password` params(user_id) → out: list [auth]
  `apps/api/src/api/routes/profiles.py`

## Middleware

- **ratelimit** (auth) — `apps/api/src/core/security/ratelimit.py`
- **auth** (auth) — `apps/api/src/services/auth.py`
- **test_register_rate_limit** (auth) — `apps/api/tests/test_register_rate_limit.py`
- **query-keys-guard.test** (auth) — `apps/web/src/hooks/query-keys-guard.test.ts`
- **authProvider** (auth) — `apps/web/src/providers/authProvider.ts`

## Source Files

Read these before implementing or modifying this subsystem:
- `apps/api/src/api/routes/auth.py`
- `apps/api/src/api/routes/oauth.py`
- `apps/api/src/api/routes/profiles.py`

---
_Back to [overview.md](./overview.md)_