# Config

## Environment Variables

- `ACCESS_TOKEN_EXPIRE_MINUTES` (has default) — apps/api/.env.example
- `APP_NAME` (has default) — apps/api/.env.example
- `ATLASSIAN_API_TOKEN` **required** — agent/skills/atlassian-rest/scripts/confluence.mjs
- `ATLASSIAN_DOMAIN` **required** — agent/skills/atlassian-rest/scripts/confluence.mjs
- `ATLASSIAN_EMAIL` **required** — agent/skills/atlassian-rest/scripts/confluence.mjs
- `CORS_ORIGINS` (has default) — apps/api/.env.example
- `DATABASE_URL` **required** — apps/api/tests/conftest.py
- `DEBUG` (has default) — apps/api/.env.example
- `DEV` **required** — agent/skills/slide-maker/deck-template/src/App.jsx
- `DOCKER_HOST` (has default) — apps/api/tests/test_nats_integration.py
- `EMBEDDED_DB_DIR` **required** — apps/api/src/db/embedded.py
- `ENVIRONMENT` (has default) — apps/api/.env.example
- `EVENT_BUS_DRIVER` (has default) — apps/api/.env.example
- `FERNET_KEYS` (has default) — apps/api/.env.example
- `FRONTEND_URL` (has default) — apps/api/.env.example
- `GEMINI_API_KEY` (has default) — agent/skills/ai-multimodal/.env.example
- `GEMINI_IMAGE_GEN_MODEL` **required** — agent/skills/ai-multimodal/scripts/gemini_batch_process.py
- `GEMINI_MODEL` **required** — agent/skills/ai-multimodal/scripts/gemini_batch_process.py
- `IMAGE_GEN_MODEL` **required** — agent/skills/ai-multimodal/scripts/gemini_batch_process.py
- `JOBS_DEFAULT_TIMEOUT_SECONDS` (has default) — apps/api/.env.example
- `JOBS_RUN_RETENTION` (has default) — apps/api/.env.example
- `JOBS_SCHEDULER_TICK_SECONDS` (has default) — apps/api/.env.example
- `MULTIMODAL_MODEL` **required** — agent/skills/ai-multimodal/scripts/gemini_batch_process.py
- `NATS_URL` (has default) — apps/api/.env.example
- `OPENAI_BASE_URL` **required** — apps/api/src/agents/llm.py
- `REFRESH_TOKEN_EXPIRE_DAYS` (has default) — apps/api/.env.example
- `SECRET_ENCRYPT_VERSION` (has default) — apps/api/.env.example
- `SECRET_KEY` (has default) — apps/api/.env.example
- `SECRET_STORE_DRIVER` (has default) — apps/api/.env.example
- `SUPERADMIN_EMAIL` (has default) — apps/api/.env.example
- `VIDEO_GEN_MODEL` **required** — agent/skills/ai-multimodal/scripts/gemini_batch_process.py
- `VITE_API_URL` (has default) — apps/web/src/providers/dataProvider.ts
- `VITE_EDIT` **required** — agent/skills/slide-maker/deck-template/src/App.jsx
- `VITE_WS_URL` (has default) — apps/web/src/providers/liveProvider.ts

## Config Files

- `agent/skills/ai-multimodal/.env.example`
- `agent/skills/slide-maker/deck-template/tailwind.config.js`
- `agent/skills/slide-maker/deck-template/vite.config.js`
- `agent/skills/slides-generator/assets/template/tailwind.config.js`
- `agent/skills/slides-generator/assets/template/vite.config.js`
- `apps/api/.env.example`
- `apps/web/.env.example`
- `apps/web/tailwind.config.js`
- `apps/web/vite.config.ts`
