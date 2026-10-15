# Test Coverage

> **35%** of routes and models are covered by tests
> 137 test files found

## Covered Routes

- GET:
- POST:
- POST:/register
- POST:/forgot-password
- POST:/verify-email
- POST:/login
- GET:/me
- DELETE:/{invitation_id}
- POST:/accept
- GET:/mine
- POST:/{invitation_id}/resend
- POST:/{invitation_id}/decline
- DELETE:/me
- GET:/events
- GET:/subscriptions
- GET:/subscriptions/{subscription_id}
- POST:/subscriptions
- PATCH:/subscriptions/{subscription_id}
- DELETE:/subscriptions/{subscription_id}
- POST:/subscriptions/{subscription_id}/rotate-secret
- GET:/deliveries
- GET:/subscriptions/{subscription_id}/deliveries
- GET:/deliveries/{delivery_id}
- POST:/deliveries/{delivery_id}/redeliver
- GET:/

## Covered Models

- ApiKey
- AuditLogEntry
- Conversation
- ConversationParticipant
- Message
- Invitation
- NotificationPreference
- Notification
- JobDefinition
- JobRun
- JobLogEntry
- OAuthAccount
- StoredSecret
- UserProfile
- WebhookSubscription
- WebhookDelivery
- User
- AuthToken
- RefreshToken
- Workspace
- Role
- WorkspaceMember
