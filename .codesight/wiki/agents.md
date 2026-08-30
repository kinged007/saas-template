# Agents

> **Navigation aid.** Route list and file locations extracted via AST. Read the source files listed below before implementing or modifying this subsystem.

The Agents subsystem handles **8 routes** and touches: db.

## Routes

- `GET` `` [db]
  `apps/api/src/api/routes/agents.py`
- `POST` `` → in: AgentCreate
  `apps/api/src/api/routes/agents.py`
- `GET` `/{agent_id}` params(agent_id)
  `apps/api/src/api/routes/agents.py`
- `PATCH` `/{agent_id}` params(agent_id)
  `apps/api/src/api/routes/agents.py`
- `DELETE` `/{agent_id}` params(agent_id) [db]
  `apps/api/src/api/routes/agents.py`
- `GET` `/{agent_id}/secrets` params(agent_id)
  `apps/api/src/api/routes/agents.py`
- `PUT` `/{agent_id}/secrets/{key}` params(agent_id, key)
  `apps/api/src/api/routes/agents.py`
- `DELETE` `/{agent_id}/secrets/{key}` params(agent_id, key) [db]
  `apps/api/src/api/routes/agents.py`

## Source Files

Read these before implementing or modifying this subsystem:
- `apps/api/src/api/routes/agents.py`

---
_Back to [overview.md](./overview.md)_