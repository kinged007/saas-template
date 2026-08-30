# Database

> **Navigation aid.** Schema shapes and field types extracted via AST. Read the actual schema source files before writing migrations or query logic.

**sqlalchemy** — 17 models

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
- `workspace_id`: unknown _(index, nullable)_
- `actor_user_id`: unknown _(nullable)_
- `resource_type`: String
- `resource_id`: str
- `action`: String
- `details`: JSON _(default)_
- `ip_address`: String _(nullable)_

### Conversation

pk: `id` (str)

- `id`: str _(pk, default)_
- `workspace_id`: str _(index)_
- `created_by_user_id`: str _(index)_
- `title`: String _(nullable)_
- `last_message_at`: DateTime _(nullable, index)_
- `last_message_preview`: String _(nullable)_

### ConversationParticipant

pk: `id` (str)

- `id`: str _(pk, default)_
- `conversation_id`: str _(index)_
- `participant_type`: String _(default, index)_
- `participant_id`: str _(index)_
- `user_id`: unknown _(nullable, index)_
- `agent_id`: unknown _(nullable, index)_
- `joined_at`: DateTime
- `last_read_at`: DateTime _(nullable)_
- `last_read_message_id`: unknown _(nullable)_
- `archived_at`: DateTime _(nullable)_

### Message

pk: `id` (str)

- `id`: str _(pk, default)_
- `conversation_id`: str _(index)_
- `sender_type`: String _(default)_
- `sender_id`: str _(index)_
- `sender_user_id`: unknown _(nullable, index)_
- `sender_agent_id`: unknown _(nullable)_
- `body`: Text
- `body_html`: Text _(nullable)_

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

### JobDefinition

pk: `id` (str)

- `id`: str _(pk, default)_
- `key`: String _(index)_
- `workspace_id`: unknown _(index, nullable)_
- `name`: String
- `description`: Text _(default)_
- `cron_schedule`: String
- `params_schema`: JSON _(default)_
- `params`: JSON _(default)_
- `enabled`: bool _(default)_
- `missed_policy`: String _(default)_
- `timeout_seconds`: Integer _(default)_
- `next_run_at`: DateTime _(nullable)_
- `last_run_at`: DateTime _(nullable)_

### JobRun

pk: `id` (str)

- `id`: str _(pk, default)_
- `definition_id`: str _(index)_
- `workspace_id`: unknown _(index, nullable)_
- `status`: String _(default, index)_
- `trigger`: String _(default)_
- `actor_user_id`: unknown _(index, nullable)_
- `params`: JSON _(default)_
- `scheduled_at`: DateTime
- `started_at`: DateTime _(nullable)_
- `finished_at`: DateTime _(nullable)_
- `duration_ms`: Integer _(nullable)_
- `error`: Text _(nullable)_
- `correlation_id`: String _(nullable)_

### JobLogEntry

pk: `id` (str)

- `id`: str _(pk, default)_
- `run_id`: str _(index)_
- `seq`: Integer _(default)_
- `ts`: DateTime
- `level`: String _(default)_
- `message`: Text

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

### UserProfile

pk: `user_id` (str) · fk: user_id

- `user_id`: str _(fk, pk)_
- `first_name`: String _(nullable)_
- `last_name`: String _(nullable)_
- `bio`: String _(nullable)_
- `phone_number`: String _(nullable)_
- `timezone`: String _(nullable)_
- `locale`: String _(nullable)_
- `date_of_birth`: Date _(nullable)_
- `website_url`: String _(nullable)_
- `location`: String _(nullable)_
- `custom_data`: JSON _(default)_

### User

pk: `id` (str)

- `id`: str _(pk, default)_
- `email`: String _(unique, index)_
- `password_hash`: String _(nullable)_
- `display_name`: String
- `avatar_url`: String _(nullable)_
- `is_active`: Boolean _(default)_
- `is_superuser`: Boolean _(default)_
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

- `apps/api/src/db/session.py` — imported by **33** files
- `apps/api/src/models/workspace.py` — imported by **20** files
- `apps/api/src/models/core.py` — imported by **13** files
- `apps/api/src/db/base.py` — imported by **10** files
- `apps/api/src/models/api_key.py` — imported by **10** files
- `apps/api/src/schemas/api.py` — imported by **10** files
- `apps/api/src/models/jobs.py` — imported by **8** files

---
_Back to [overview.md](./overview.md)_