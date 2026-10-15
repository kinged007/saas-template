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
- expires_at: DateTime (nullable, index)
- revoked_at: DateTime (nullable)
- usage_count: Integer (default)
- usage_quota: Integer (nullable)
- usage_window_count: Integer (default)
- usage_window_start: DateTime (nullable)

### AuditLogEntry
- id: str (pk, default)
- workspace_id: unknown (index, nullable)
- actor_user_id: unknown (nullable)
- resource_type: String
- resource_id: str
- action: String
- details: JSON (default)
- ip_address: String (nullable)

### Conversation
- id: str (pk, default)
- workspace_id: str (index)
- created_by_user_id: str (index)
- title: String (nullable)
- last_message_at: DateTime (nullable, index)
- last_message_preview: String (nullable)

### ConversationParticipant
- id: str (pk, default)
- conversation_id: str (index)
- participant_type: String (default, index)
- participant_id: str (index)
- user_id: unknown (nullable, index)
- agent_id: unknown (nullable, index)
- joined_at: DateTime
- last_read_at: DateTime (nullable)
- last_read_message_id: unknown (nullable)
- archived_at: DateTime (nullable)

### Message
- id: str (pk, default)
- conversation_id: str (index)
- sender_type: String (default)
- sender_id: str (index)
- sender_user_id: unknown (nullable, index)
- sender_agent_id: unknown (nullable)
- body: Text
- body_html: Text (nullable)

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

### NotificationPreference
- id: str (pk, default)
- user_id: str (index)
- type: String
- channel: String (default)
- digest_enabled: Boolean (default)
- unsubscribe_token: String (index, nullable)

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

### OAuthAccount
- id: str (pk, default)
- user_id: str (fk, index)
- provider: String
- subject: String

### StoredSecret
- id: str (pk, default)
- workspace_id: str (index)
- secret_key: String (index)
- kind: String
- label: String (nullable)
- ciphertext: Text
- key_version: Integer
- meta: JSON (nullable, default)
- expires_at: DateTime (nullable)

### UserTotpCredential
- user_id: str (fk, pk)
- secret_ciphertext: Text
- last_counter: Integer (nullable)
- backup_codes: JSON (default)

### UserProfile
- user_id: str (fk, pk)
- first_name: String (nullable)
- last_name: String (nullable)
- bio: String (nullable)
- phone_number: String (nullable)
- timezone: String (nullable)
- locale: String (nullable)
- date_of_birth: Date (nullable)
- website_url: String (nullable)
- location: String (nullable)
- custom_data: JSON (default)

### WebhookSubscription
- id: str (pk, default)
- workspace_id: str (index)
- url: String
- events: JSON (default)
- active: Boolean (default)
- created_by_user_id: unknown (nullable)

### WebhookDelivery
- id: str (pk, default)
- subscription_id: str (index)
- workspace_id: str (index)
- event_type: String
- subject: String
- payload: JSON (default)
- status: String (default, index)
- attempt_count: Integer (default)
- next_retry_at: DateTime (nullable)
- last_attempt_at: DateTime (nullable)
- response_status: Integer (nullable)
- error: Text (nullable)
- event_id: String (nullable)
- correlation_id: String (nullable)

### User
- id: str (pk, default)
- email: String (unique, index)
- password_hash: String (nullable)
- display_name: String
- avatar_url: String (nullable)
- is_active: Boolean (default)
- is_superuser: Boolean (default)
- last_login_at: DateTime (nullable)
- email_verified_at: DateTime (nullable)
- totp_enabled: Boolean (default)

### AuthToken
- id: str (pk, default)
- user_id: str (index)
- purpose: String
- token_hash: String (unique, index)
- expires_at: DateTime
- consumed_at: DateTime (nullable)

### RefreshToken
- id: str (pk, default)
- user_id: str (index)
- token_hash: String (unique, index)
- expires_at: DateTime
- revoked_at: DateTime (nullable)
- ip_address: String (nullable)
- user_agent: String (nullable)

### Workspace
- id: str (pk, default)
- name: String
- slug: String (unique, index)
- description: String (nullable)
- created_by_user_id: str (index)
- flags: JSON (default)

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
