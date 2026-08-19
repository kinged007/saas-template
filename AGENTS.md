# tenant-flex-new — Project Context

**Stack:** fastapi | sqlalchemy | typescript
**Monorepo:** api, tenantflex-web

32 routes | 8 models | 23 env vars | 187 import links

**API areas:** /providers/{provider}, /{connection_id}, /register, /login, /refresh, /logout, /me, /oauth/providers, /oauth/{provider}, /oauth/exchange

**High-impact files** (change carefully):
- apps/web/src/types.ts (imported by 13 files)
- apps/api/src/tenantflex/db/session.py (imported by 11 files)
- apps/api/src/tenantflex/api/deps.py (imported by 9 files)
- apps/api/src/tenantflex/models/core.py (imported by 9 files)
- apps/api/src/tenantflex/settings.py (imported by 8 files)

**Required env vars:** DATABASE_URL, EMBEDDED_DB_DIR, MICROSOFT_CLIENT_ID, MICROSOFT_CLIENT_SECRET, OKTA_CLIENT_ID, OKTA_CLIENT_SECRET

---

## Agent Instructions

This project uses codesight for structured AI context. Follow these steps before implementing:
1. Read `.codesight/wiki/index.md` for project orientation (~200 tokens)
2. Read `.codesight/wiki/overview.md` for architecture overview (~500 tokens)
3. Read the relevant domain article, then open the source files listed in it
4. Read `.codesight/CODESIGHT.md` for the full context map

**Do not explore the file tree blindly.** The codesight context map already contains:
routes, schema, components, libraries, config, middleware, and dependency graph.

**Before modifying any file:** check `.codesight/graph.md` for blast radius.
Files with high import counts affect many downstream modules — change carefully.

Routes marked `[inferred]` were detected via regex and may have lower precision.
If any source file shows ⚠ in a wiki article, re-run `npx codesight --wiki` before proceeding.