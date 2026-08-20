# Config

## Environment Variables

- `ACCESS_TOKEN_EXPIRE_MINUTES` (has default) — apps/api/.env.example
- `APP_NAME` (has default) — apps/api/.env.example
- `CORS_ORIGINS` (has default) — apps/api/.env.example
- `DATABASE_URL` **required** — apps/api/tests/conftest.py
- `DEBUG` (has default) — apps/api/.env.example
- `DOCKER_HOST` (has default) — apps/api/tests/test_nats_integration.py
- `EMBEDDED_DB_DIR` (has default) — apps/api/.env
- `ENVIRONMENT` (has default) — apps/api/.env.example
- `EVENT_BUS_DRIVER` (has default) — apps/api/.env.example
- `FERNET_KEYS` (has default) — apps/api/.env.example
- `FRONTEND_URL` (has default) — apps/api/.env.example
- `NATS_URL` (has default) — apps/api/.env.example
- `REFRESH_TOKEN_EXPIRE_DAYS` (has default) — apps/api/.env.example
- `SECRET_ENCRYPT_VERSION` (has default) — apps/api/.env.example
- `SECRET_KEY` (has default) — apps/api/.env.example
- `SECRET_STORE_DRIVER` (has default) — apps/api/.env.example
- `VITE_API_URL` (has default) — apps/web/src/providers/dataProvider.ts
- `VITE_WS_URL` (has default) — apps/web/src/providers/liveProvider.ts

## Config Files

- `apps/api/.env.example`
- `apps/web/.env.example`
- `apps/web/tailwind.config.js`
- `apps/web/vite.config.ts`
