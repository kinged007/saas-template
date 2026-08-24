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
- `GET` `/unread-count` params()
- `GET` `/permission-catalog` params()
- `GET` `/` params() ✓
