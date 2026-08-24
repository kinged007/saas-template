# Schema

### ApiKey
- id: str (pk, default)
- workspace_id: str (index)
- name: String
- key_prefix: String
- key_hash: String (unique, index)
- permissions: JSON (default)
- created_by_user_id: str (index)
- last_used_at: DateTime (nullable)
- revoked_at: DateTime (nullable)

### AuditLogEntry
- id: str (pk, default)
- workspace_id: unknown (index, nullable)
- actor_user_id: unknown (nullable)
- resource_type: String
- resource_id: str
- action: String
- details: JSON (default)
- ip_address: String (nullable)

### Invitation
- id: str (pk, default)
- workspace_id: str (index)
- email: String
- role_id: str
- invited_by_user_id: str
- token: String (unique, index)
- status: String (default)
- expires_at: DateTime
- accepted_at: DateTime (nullable)

### Notification
- id: str (pk, default)
- user_id: str (index)
- workspace_id: str (index)
- type: String
- title: String
- body: String (nullable)
- payload: JSON (default)
- acknowledged_at: DateTime (nullable)

### JobDefinition
- id: str (pk, default)
- key: String (index)
- workspace_id: unknown (index, nullable)
- name: String
- description: Text (default)
- cron_schedule: String
- params_schema: JSON (default)
- params: JSON (default)
- enabled: bool (default)
- missed_policy: String (default)
- timeout_seconds: Integer (default)
- next_run_at: DateTime (nullable)
- last_run_at: DateTime (nullable)

### JobRun
- id: str (pk, default)
- definition_id: str (index)
- workspace_id: unknown (index, nullable)
- status: String (default, index)
- trigger: String (default)
- actor_user_id: unknown (index, nullable)
- params: JSON (default)
- scheduled_at: DateTime
- started_at: DateTime (nullable)
- finished_at: DateTime (nullable)
- duration_ms: Integer (nullable)
- error: Text (nullable)
- correlation_id: String (nullable)

### JobLogEntry
- id: str (pk, default)
- run_id: str (index)
- seq: Integer (default)
- ts: DateTime
- level: String (default)
- message: Text

### StoredSecret
- id: str (pk, default)
- workspace_id: str (index)
- secret_key: String (index)
- kind: String
- label: String (nullable)
- ciphertext: Text
- key_version: Integer
- meta: JSON (default)
- expires_at: DateTime (nullable)

### User
- id: str (pk, default)
- email: String (unique, index)
- password_hash: String (nullable)
- display_name: String
- avatar_url: String (nullable)
- is_active: Boolean (default)
- is_superuser: Boolean (default)
- last_login_at: DateTime (nullable)

### RefreshToken
- id: str (pk, default)
- user_id: str (index)
- token_hash: String (unique, index)
- expires_at: DateTime
- revoked_at: DateTime (nullable)

### Workspace
- id: str (pk, default)
- name: String
- slug: String (unique, index)
- description: String (nullable)
- created_by_user_id: str (index)

### Role
- id: str (pk, default)
- workspace_id: str (index)
- name: String
- description: String (nullable)
- permissions: JSON (default)
- system: Boolean (default)

### WorkspaceMember
- id: str (pk, default)
- workspace_id: str (index)
- user_id: str (index)
- role_id: str (index)
- status: String (default)
