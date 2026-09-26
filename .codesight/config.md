# Config

## Environment Variables

- `ACCESS_TOKEN_EXPIRE_MINUTES` (has default) — apps/api/.env.example
- `APP_NAME` (has default) — apps/api/.env.example
- `AUDIT_LOG_RETENTION_DAYS` (has default) — apps/api/.env.example
- `AUTH_RATE_LIMIT_MAX_ATTEMPTS` (has default) — apps/api/.env.example
- `AUTH_RATE_LIMIT_WINDOW_SECONDS` (has default) — apps/api/.env.example
- `CORS_ORIGINS` (has default) — apps/api/.env.example
- `DATABASE_URL` **required** — apps/api/tests/conftest.py
- `DEBUG` (has default) — apps/api/.env.example
- `DOCKER_HOST` (has default) — apps/api/tests/test_nats_integration.py
- `EMAIL_DRIVER` (has default) — apps/api/.env.example
- `EMAIL_FROM` **required** — apps/api/.env.example
- `EMBEDDED_DB_DIR` **required** — apps/api/src/db/embedded.py
- `ENVIRONMENT` (has default) — apps/api/.env.example
- `EVENT_BUS_DRIVER` (has default) — apps/api/.env.example
- `FERNET_KEYS` (has default) — apps/api/.env.example
- `FRONTEND_URL` (has default) — apps/api/.env.example
- `JOBS_DEFAULT_TIMEOUT_SECONDS` (has default) — apps/api/.env.example
- `JOBS_LOG_RETENTION_DAYS` (has default) — apps/api/.env.example
- `JOBS_RUN_RETENTION` (has default) — apps/api/.env.example
- `JOBS_SCHEDULER_TICK_SECONDS` (has default) — apps/api/.env.example
- `NATS_URL` (has default) — apps/api/.env.example
- `NOTIFICATIONS_RETENTION_DAYS` (has default) — apps/api/.env.example
- `REFRESH_TOKEN_EXPIRE_DAYS` (has default) — apps/api/.env.example
- `SECRET_ENCRYPT_VERSION` (has default) — apps/api/.env.example
- `SECRET_KEY` (has default) — apps/api/.env.example
- `SECRET_STORE_DRIVER` (has default) — apps/api/.env.example
- `SMTP_HOST` (has default) — apps/api/.env.example
- `SMTP_PASSWORD` **required** — apps/api/.env.example
- `SMTP_PORT` (has default) — apps/api/.env.example
- `SMTP_TIMEOUT_S` (has default) — apps/api/.env.example
- `SMTP_USE_TLS` (has default) — apps/api/.env.example
- `SMTP_USERNAME` **required** — apps/api/.env.example
- `SUPERADMIN_EMAIL` **required** — apps/api/.env.example
- `VITE_API_URL` (has default) — apps/web/src/providers/dataProvider.ts
- `VITE_WS_URL` (has default) — apps/web/src/providers/liveProvider.ts

## Config Files

- `apps/api/.env.example`
- `apps/web/.env.example`
- `apps/web/tailwind.config.js`
- `apps/web/vite.config.ts`
