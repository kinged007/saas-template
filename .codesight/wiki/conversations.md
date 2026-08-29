# Conversations

> **Navigation aid.** Route list and file locations extracted via AST. Read the source files listed below before implementing or modifying this subsystem.

The Conversations subsystem handles **8 routes**.

## Routes

- `GET` `/unread-count` → in: st
  `apps/api/src/api/routes/conversations.py`
- `GET` `/{conversation_id}` params(conversation_id) → in: st
  `apps/api/src/api/routes/conversations.py`
- `PATCH` `/{conversation_id}` params(conversation_id)
  `apps/api/src/api/routes/conversations.py`
- `PATCH` `/{conversation_id}/read` params(conversation_id)
  `apps/api/src/api/routes/conversations.py`
- `PATCH` `/{conversation_id}/unread` params(conversation_id)
  `apps/api/src/api/routes/conversations.py`
- `PATCH` `/{conversation_id}/archive` params(conversation_id)
  `apps/api/src/api/routes/conversations.py`
- `GET` `/{conversation_id}/messages` params(conversation_id) → in: st
  `apps/api/src/api/routes/conversations.py`
- `POST` `/{conversation_id}/messages` params(conversation_id) → in: ConversationCreate
  `apps/api/src/api/routes/conversations.py`

## Source Files

Read these before implementing or modifying this subsystem:
- `apps/api/src/api/routes/conversations.py`

---
_Back to [overview.md](./overview.md)_