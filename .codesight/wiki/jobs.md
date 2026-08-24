# Jobs

> **Navigation aid.** Route list and file locations extracted via AST. Read the source files listed below before implementing or modifying this subsystem.

The Jobs subsystem handles **11 routes** and touches: auth.

## Routes

- `GET` `/global`
  `apps/api/src/api/routes/jobs.py`
- `GET` `/global/{definition_id}` params(definition_id)
  `apps/api/src/api/routes/jobs.py`
- `PATCH` `/global/{definition_id}` params(definition_id)
  `apps/api/src/api/routes/jobs.py`
- `POST` `/global/{definition_id}/execute` params(definition_id)
  `apps/api/src/api/routes/jobs.py`
- `GET` `/global/{definition_id}/runs` params(definition_id)
  `apps/api/src/api/routes/jobs.py`
- `GET` `/runs/{run_id}` params(run_id)
  `apps/api/src/api/routes/jobs.py`
- `GET` `/runs/{run_id}/logs` params(run_id)
  `apps/api/src/api/routes/jobs.py`
- `GET` `/{definition_id}` params(definition_id) [auth]
  `apps/api/src/api/routes/jobs.py`
- `PATCH` `/{definition_id}` params(definition_id) [auth]
  `apps/api/src/api/routes/jobs.py`
- `POST` `/{definition_id}/execute` params(definition_id) [auth]
  `apps/api/src/api/routes/jobs.py`
- `GET` `/{definition_id}/runs` params(definition_id) [auth]
  `apps/api/src/api/routes/jobs.py`

## Source Files

Read these before implementing or modifying this subsystem:
- `apps/api/src/api/routes/jobs.py`

---
_Back to [overview.md](./overview.md)_