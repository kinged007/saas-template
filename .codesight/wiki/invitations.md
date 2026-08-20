# Invitations

> **Navigation aid.** Route list and file locations extracted via AST. Read the source files listed below before implementing or modifying this subsystem.

The Invitations subsystem handles **4 routes** and touches: db, auth.

## Routes

- `DELETE` `/{invitation_id}` params(invitation_id) [db]
  `apps/api/src/api/routes/invitations.py`
- `POST` `/accept` → in: InvitationCreate [auth, db]
  `apps/api/src/api/routes/invitations.py`
- `GET` `/mine`
  `apps/api/src/api/routes/invitations.py`
- `POST` `/{invitation_id}/decline` params(invitation_id) → in: InvitationCreate
  `apps/api/src/api/routes/invitations.py`

## Source Files

Read these before implementing or modifying this subsystem:
- `apps/api/src/api/routes/invitations.py`

---
_Back to [overview.md](./overview.md)_