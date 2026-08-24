# Example: connecting an external service (Okta)

A worked example of integrating an external OAuth service into the template:
connecting an Okta **Workforce Identity org** so admins can review the org's
application catalog. This documents the OAuth service-app pattern, the
encrypted secret store, and the error-handling conventions you'd reuse for
any external provider integration.

- Provider code: `OKTA`
- Tests: `apps/api/tests/test_okta.py`
- Docs (Okta): [Implement OAuth for Okta with a service app](https://developer.okta.com/docs/guides/implement-oauth-for-okta-serviceapp/main/),
  [Apps API](https://developer.okta.com/docs/api/openapi/okta-management/management/tags/application/other/listapplications),
  [OAuth 2.0 scopes](https://developer.okta.com/docs/api/oauth2/),
  [Roles](https://developer.okta.com/docs/api/openapi/okta-management/guides/roles/)

> **Note:** the Okta provider integration was part of an earlier iteration of
> this template. The API surface it used (connections / applications routes)
> has since been removed — this doc is kept as a reference for the OAuth
> service-app + encrypted-secret pattern.

## What it does today

| Capability | Status |
|---|---|
| Test connection (token + catalog reachability) | ✅ |
| List all applications (incl. inactive) | ✅ |
| Application detail review (OIDC redirect URIs, SAML ACS URL, signing key, OAuth client) | ✅ |
| Create / manage applications | 🔜 needs `okta.apps.manage` scope + APP_ADMIN role |

## Okta-side setup (one-time, per tenant) — verified end-to-end

### 1. Create the app
Okta Admin Console → **Applications → Create App Integration** → **API Services**.
The **Client Credentials** grant type is enabled automatically.

### 2. Set client authentication to Public key/Private key
App → **General** tab → **Client Credentials** section → **Edit** →
Client authentication → **Public key/Private key** (this is what
`private_key_jwt` is called in the console).

> ⚠️ If the client is left on the default `client_secret_basic` (or has no
> secret), token requests fail with the generic
> `Client authentication failed. Either the client or the client credentials
> are invalid.`

### 3. Register the public key (JWK JSON only)
With **Public key/Private key** selected, **Add key** → paste your public key.
**Okta's paste dialog only accepts JWK JSON — not PEM — and the JSON must
include a `kid` field.** Example (from a keypair generated for the app):

```json
{
  "kty": "RSA",
  "use": "sig",
  "alg": "RS256",
  "n": "<base64url modulus>",
  "e": "AQAB",
  "kid": "<your-key-id>"
}
```

Generate the JWK from the same keypair whose private half goes into the
connection (see `demo/okta-fresh-public-key.json` /
`demo/okta-fresh-private-key.pem` for a ready-made pair).

### 4. Grant API scopes
App → **Okta API Scopes** tab → **Grant**:
- `okta.apps.read` — view the application catalog
- `okta.apps.manage` — create/update apps and their credentials/keys
- (optional) `okta.orgs.read` — lets connection tests show the org display name

Only a **Super Admin** can grant scopes.

### 5. Assign an admin role (required — the minimum is APP_ADMIN)
App → **Admin Roles** tab → **Edit assignments** → **Application Administrator**
→ Save.

Service apps get **no admin role automatically**, and without one the API
rejects every request with `403 You do not have permission to perform the
requested action` even when the token carries the right scopes.

**Least privilege:** `APP_ADMIN` (Application Administrator) is
the minimum **standard** role for reading, creating, and managing all
applications (settings, credentials, signing keys). For tighter control,
create a **custom admin role** containing only the `okta.apps.read` and
`okta.apps.manage` permissions scoped to an apps resource set (see
[Permissions in Okta](https://developer.okta.com/docs/api/openapi/okta-management/guides/permissions/)).
Super Administrator is **not** required.

### 6. Consent must be TRUSTED
Some service apps default to `consent_method: REQUIRED`, which blocks the
client-credentials flow with
`consent_required: You are not allowed any of the requested scopes.`
The console does not reliably expose this for service apps — set it via the
Management API with an SSWS token:

```bash
curl -X GET  "https://{tenant}.okta.com/api/v1/apps/{clientId}" \
  -H "Authorization: SSWS {token}" -o app.json
# edit app.json: set settings.oauthClient.consent_method = "TRUSTED"
curl -X PUT  "https://{tenant}.okta.com/api/v1/apps/{clientId}" \
  -H "Authorization: SSWS {token}" -H "Content-Type: application/json" -d @app.json
```

### 7. Test the connection
In the app: connection → **Test**. Expected: `Connected to Okta org.`
with the org name as the tenant hint.

## Connection fields

| Field | Required | Value |
|---|---|---|
| Provider | — | `OKTA` |
| Authority | ✅ | `https://<tenant>.okta.com` (the org API domain, **not** the `-admin` console URL) |
| Client ID | ✅ | from the app's General tab |
| Client secret | ✅ | the app's **private key (PEM)** — the app auto-detects PEM and uses private_key_jwt assertions; a plain secret uses client_secret_post |
| Key ID (kid) | for PEM | the Key ID shown in the app's **Public keys** table (must match the registered JWK's kid) |
| Scope | defaulted | `okta.apps.manage` if left empty |
| Endpoint | ✅ | `https://<tenant>.okta.com` |

> ⚠️ **Common mistakes:** `https://your-tenant-admin.okta.com` is the console,
> not the API — requests to it return HTML and fail. An **empty scope** makes
> the token request fail with `consent_required` — the app now falls back to
> the provider default, but keep the scope field populated.

### Validation on save

Each provider validates connections on create **and** update (HTTP 400 with
the reason):

- **Okta** — `authority`, `endpoint`, `client_id`, `client_secret` required;
  `scope` falls back to the default. Placeholder domains (`your-tenant.okta.com`,
  `<...>`) and `-admin` console URLs are rejected; a PEM secret requires a
  `key_id`.
- **Entra** — `authority`, `client_id`, `client_secret` required; `scope` and
  `endpoint` fall back to Graph defaults.

## How it works

### Authentication

Client-credentials token from the **org authorization server**
(`POST /oauth2/v1/token`) with either a client secret or an RFC 7523 client
assertion signed by the registered key. Each retry mints a **fresh assertion**
(the `jti` claim is single-use).

### DPoP (RFC 9449) — handled automatically

Orgs that enforce DPoP (and bound tokens) are handled transparently:

1. Plain request → on `invalid_dpop_proof`, an ephemeral P-256 key is generated
   and every request carries a signed `DPoP` proof (adopting `dpop_nonce` when
   demanded, and `ath` for resource requests).
2. DPoP-bound tokens are sent with the **`Authorization: DPoP`** scheme (Okta's
   Management API rejects `Bearer` for bound tokens).
3. Proof `htu` claims are sent **without** the query string (Okta rejects
   query-bearing `htu`).

### Endpoints used

| Product call | Okta API | Notes |
|---|---|---|
| `test_connection` | `GET /api/v1/org` then fallback `GET /api/v1/apps?limit=1` | org hint needs `okta.orgs.read`; falls back to catalog check on 401/403 |
| `list_applications` | `GET /api/v1/apps?limit=200&includeNonDeleted=true[&q=<search>]` | `includeNonDeleted=true` shows inactive apps; `q` is a startsWith match on name/label; pages followed via `Link: rel="next"` |
| `get_application` | `GET /api/v1/apps/{appId}` | — |

### Normalized mapping (canonical application schema)

Every provider maps its payload onto the **canonical schema** defined in
`providers/base.py` (`ApplicationSummary` / `ApplicationDetail`) — the UI
consumes only these fields, and the provider's original payload is preserved
unmodified in `raw`.

| SaaS template shape | Okta source |
|---|---|
| `id` | `id` (e.g. `0oa…`) |
| `display_name` | `label` (falls back to `name`) |
| `app_type` | always `application` (Okta has no service-principal concept) |
| `status` | `status` (ACTIVE / INACTIVE) |
| `sign_on_mode` | `signOnMode` (OPENID_CONNECT, SAML_2_0, SWA, …) |
| `redirect_uris` | `settings.oauthClient.redirect_uris` + `post_logout_redirect_uris` |
| `identifier_uris` | `settings.signOn.ssoAcsUrl` (SAML), `settings.oauthClient.client_uri` (OIDC) |
| `app_roles` | none (empty; Entra maps `appRoles`) |
| `permissions` | none (empty; Entra maps `requiredResourceAccess` → `{resource_app_id, scopes}`) |
| `credentials` | `credentials.signing.kid` → `{key_id, type: "signing_key"}`; `credentials.oauthClient` → `{client_id, token_endpoint_auth_method, type: "oauth_client"}` |
| `raw` | full original app object (JSON view / reference) |

## Error guide: what each failure means

| Error from Okta | Meaning | Fix |
|---|---|---|
| `Client authentication failed…` (generic) | client auth method is `client_secret_basic` with no/old secret, or assertion not accepted | Set **Public key/Private key** (step 2); check key/kid match |
| `The client_assertion JWT kid is invalid.` | kid in the assertion isn't a registered key | Copy the kid from the app's **Public keys** table into the connection |
| `The client_assertion signature is invalid.` | private key doesn't match the registered public key | Re-register the public key that matches your private key |
| `The client_assertion token has already been used.` | assertion `jti` replayed (retries reuse it) | Fixed in provider (fresh assertion per attempt); restart API |
| `consent_required: You are not allowed any of the requested scopes.` | app consent is REQUIRED, or the scope is empty | Set `consent_method=TRUSTED` (step 6); keep the scope populated |
| `You do not have permission…` (403, E0000006) | no admin role on the service app | Assign **Application Administrator** (step 5) |
| `The DPoP proof JWT header is missing.` / `use_dpop_nonce` | org enforces DPoP | Automatic in provider (restart API to be sure) |
| `'htu' claim in the DPoP proof JWT is invalid.` | query string in the proof URL | Fixed in provider (htu sent without query) |
| unexpected non-JSON response | called the `-admin` console URL | Use the org API domain |

## Failure behavior (no 500s)

All provider calls fail into structured errors: `test_connection` always
returns a readable result (never a 500); `list_applications` /
`get_application` raise `ProviderError` which the API layer converts to
HTTP 400 with the same readable message.
