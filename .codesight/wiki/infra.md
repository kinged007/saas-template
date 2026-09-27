# Infra

> **Navigation aid.** Route list and file locations extracted via AST. Read the source files listed below before implementing or modifying this subsystem.

The Infra subsystem handles **4 routes**.

## Routes

- `GET` `/healthz`
  `apps/api/src/api/routes/meta.py`
- `GET` `/metrics`
  `apps/api/src/api/routes/meta.py`
- `GET` `/readyz`
  `apps/api/src/api/routes/meta.py`
- `GET` `/`
  `apps/api/src/main.py`

## Source Files

Read these before implementing or modifying this subsystem:
- `apps/api/src/api/routes/meta.py`
- `apps/api/src/main.py`

---
_Back to [overview.md](./overview.md)_