# Database

> **Navigation aid.** Schema shapes and field types extracted via AST. Read the actual schema source files before writing migrations or query logic.

**sqlalchemy** — 10 models

### ApiKey

pk: `id` (str)

- `id`: str _(pk, default)_
- `workspace_id`: str _(index)_
- `name`: String
- `key_prefix`: String
- `key_hash`: String _(unique, index)_
- `permissions`: JSON _(default)_
- `created_by_user_id`: str _(index)_
- `last_used_at`: DateTime _(nullable)_
- `revoked_at`: DateTime _(nullable)_

### AuditLogEntry

pk: `id` (str)

- `id`: str _(pk, default)_
- `workspace_id`: str _(index)_
- `actor_user_id`: unknown _(nullable)_
- `resource_type`: String
- `resource_id`: str
- `action`: String
- `details`: JSON _(default)_
- `ip_address`: String _(nullable)_

### Invitation

pk: `id` (str)

- `id`: str _(pk, default)_
- `workspace_id`: str _(index)_
- `email`: String
- `role_id`: str
- `invited_by_user_id`: str
- `token`: String _(unique, index)_
- `status`: String _(default)_
- `expires_at`: DateTime
- `accepted_at`: DateTime _(nullable)_

### Notification

pk: `id` (str)

- `id`: str _(pk, default)_
- `user_id`: str _(index)_
- `workspace_id`: str _(index)_
- `type`: String
- `title`: String
- `body`: String _(nullable)_
- `payload`: JSON _(default)_
- `acknowledged_at`: DateTime _(nullable)_

### StoredSecret

pk: `id` (str)

- `id`: str _(pk, default)_
- `workspace_id`: str _(index)_
- `secret_key`: String _(index)_
- `kind`: String
- `label`: String _(nullable)_
- `ciphertext`: Text
- `key_version`: Integer
- `meta`: JSON _(default)_
- `expires_at`: DateTime _(nullable)_

### User

pk: `id` (str)

- `id`: str _(pk, default)_
- `email`: String _(unique, index)_
- `password_hash`: String _(nullable)_
- `display_name`: String
- `avatar_url`: String _(nullable)_
- `is_active`: Boolean _(default)_
- `last_login_at`: DateTime _(nullable)_

### RefreshToken

pk: `id` (str)

- `id`: str _(pk, default)_
- `user_id`: str _(index)_
- `token_hash`: String _(unique, index)_
- `expires_at`: DateTime
- `revoked_at`: DateTime _(nullable)_

### Workspace

pk: `id` (str)

- `id`: str _(pk, default)_
- `name`: String
- `slug`: String _(unique, index)_
- `description`: String _(nullable)_
- `created_by_user_id`: str _(index)_

### Role

pk: `id` (str)

- `id`: str _(pk, default)_
- `workspace_id`: str _(index)_
- `name`: String
- `description`: String _(nullable)_
- `permissions`: JSON _(default)_
- `system`: Boolean _(default)_

### WorkspaceMember

pk: `id` (str)

- `id`: str _(pk, default)_
- `workspace_id`: str _(index)_
- `user_id`: str _(index)_
- `role_id`: str _(index)_
- `status`: String _(default)_

## Schema Source Files

Read and edit these files when adding columns, creating migrations, or changing relations:

- `apps/api/src/db/session.py` — imported by **16** files
- `apps/api/src/models/workspace.py` — imported by **12** files
- `apps/api/src/models/core.py` — imported by **8** files
- `apps/api/src/db/base.py` — imported by **7** files
- `apps/api/src/schemas/api.py` — imported by **7** files
- `apps/api/src/models/api_key.py` — imported by **5** files

---
_Back to [overview.md](./overview.md)_