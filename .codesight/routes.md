# Routes

## CRUD Resources

- **``** GET | POST | GET/:id | PATCH/:id | DELETE/:id

## Other Routes

- `POST` `/register` params() → in: RegisterRequest, out: TokenResponse [auth]
- `POST` `/login` params() → in: RegisterRequest, out: TokenResponse [auth]
- `POST` `/refresh` params() → in: RegisterRequest, out: TokenResponse [auth]
- `POST` `/logout` params() → in: RegisterRequest, out: TokenResponse [auth]
- `GET` `/me` params() → out: TokenResponse
- `POST` `/accept` params() → in: InvitationCreate [auth]
- `GET` `/mine` params()
- `POST` `/{invitation_id}/decline` params(invitation_id) → in: InvitationCreate
- `GET` `/healthz` params()
- `GET` `/readyz` params()
- `GET` `/unread-count` params()
- `GET` `/permission-catalog` params()
- `GET` `/` params() ✓
