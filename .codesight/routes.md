# Routes

## CRUD Resources

- **``** GET | POST | GET/:id | PATCH/:id | DELETE/:id
- **`/global`** GET | GET/:id | PATCH/:id → Global

## Other Routes

- `GET` `/effective-permissions` params()
- `POST` `/register` params() → in: RegisterRequest, out: TokenResponse [auth]
- `POST` `/login` params() → in: RegisterRequest, out: TokenResponse [auth]
- `POST` `/refresh` params() → in: RegisterRequest, out: TokenResponse [auth]
- `POST` `/logout` params() → in: RegisterRequest, out: TokenResponse [auth]
- `GET` `/me` params() → out: TokenResponse
- `GET` `/unread-count` params() → in: st
- `PATCH` `/{conversation_id}/read` params(conversation_id)
- `PATCH` `/{conversation_id}/unread` params(conversation_id)
- `PATCH` `/{conversation_id}/archive` params(conversation_id)
- `GET` `/{conversation_id}/messages` params(conversation_id) → in: st
- `POST` `/{conversation_id}/messages` params(conversation_id) → in: ConversationCreate
- `POST` `/accept` params() → in: InvitationCreate [auth, db]
- `GET` `/mine` params()
- `POST` `/{invitation_id}/decline` params(invitation_id) → in: InvitationCreate
- `POST` `/global/{definition_id}/execute` params(definition_id)
- `GET` `/global/{definition_id}/runs` params(definition_id)
- `GET` `/runs/{run_id}` params(run_id)
- `GET` `/runs/{run_id}/logs` params(run_id)
- `POST` `/{definition_id}/execute` params(definition_id) [auth]
- `GET` `/{definition_id}/runs` params(definition_id) [auth]
- `GET` `/healthz` params()
- `GET` `/readyz` params()
- `GET` `/me/profile` params() → in: Use
- `PUT` `/me/profile` params() → in: ProfileUpdate [db]
- `PATCH` `/me/profile` params() → in: ProfileUpdate [db]
- `GET` `/users/{user_id}/profile` params(user_id) → in: Use
- `GET` `/me/export` params() → in: Use
- `GET` `/users/{user_id}/export` params(user_id) → in: Use
- `DELETE` `/me` params() → in: DeleteMeRequest [db]
- `DELETE` `/users/{user_id}` params(user_id) → in: DeleteMeRequest [db]
- `GET` `/permission-catalog` params()
- `GET` `/` params() ✓
