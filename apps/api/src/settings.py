import os
import re
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.email.base import EmailDriver  # noqa: E402  (base has no settings import)
from src.events.subjects import EventBusDriver


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", os.path.expanduser("~/.config/saas-template/.env")),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: str = "development"
    app_name: str = "saas-template-api"
    debug: bool = False

    # Database. Empty → embedded PostgreSQL (pgserver; dev, no external deps).
    # Set DATABASE_URL (e.g. managed postgres) to override in production.
    database_url: str = ""

    # USE_SQLITE=1 → file DB at apps/api/dev.db instead of embedded postgres.
    # Per-checkout file, so multiple worktrees don't share a server or data
    # dir; startup is instant (no postgres boot). Explicit DATABASE_URL wins.
    use_sqlite: bool = False

    @field_validator("use_sqlite", mode="before")
    @classmethod
    def _blank_string_is_unset(cls, v):
        # ponytail: None would need Optional[bool]; False equals the default, add when it changes.
        return False if isinstance(v, str) and not v.strip() else v

    # Security
    secret_key: str = "dev-secret-change-me"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7
    # Browser session refresh cookie (HttpOnly; JS can never read it).
    # refresh_cookie_secure=None (default) → Secure on https requests; plain http
    # falls back to Secure unless ENVIRONMENT is development or test.
    refresh_cookie_name: str = "st_refresh"
    refresh_cookie_domain: str = ""
    refresh_cookie_path: str = "/api/v1/auth"
    refresh_cookie_secure: bool | None = None
    # Comma-separated Fernet keys (encryption key chosen by
    # SECRET_ENCRYPT_VERSION, rest = decryption/rotation history)
    fernet_keys: str = "dev-fernet-key-change-me-00000"
    # 1-based index into FERNET_KEYS used to encrypt NEW secrets. Rotation:
    # append the new key to FERNET_KEYS and bump this to its position — old
    # envelopes keep their version and still decrypt.
    secret_encrypt_version: int = 1
    # Secret store driver: "db" (encrypted table) | "vault" (future adapter)
    secret_store_driver: str = "db"

    # Events
    event_bus_driver: EventBusDriver = EventBusDriver.INPROCESS
    nats_url: str = "nats://localhost:4222"

    # Email: console (dev log + in-memory capture) | smtp (real delivery)
    email_driver: EmailDriver = EmailDriver.CONSOLE
    email_from: str = ""
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = True
    smtp_timeout_s: float = 10.0

    # CORS / frontend. cors_origins is comma-separated; an entry containing `*`
    # is a pattern, where `*` stands for any run of origin characters and the
    # scheme is optional (`*.example.com`, `http://localhost:*`). frontend_url
    # is the single base URL for the links in emails and OAuth redirects.
    cors_origins: str = "http://localhost:5173"
    frontend_url: str = "http://localhost:5173"

    @field_validator("frontend_url", mode="before")
    @classmethod
    def _frontend_url_keeps_first_concrete_entry(cls, v):
        # Emails and redirects need one real URL, so a wildcard entry (or a
        # copied comma list) resolves to the first origin without a `*`, and
        # to the default when every entry is a pattern.
        if not isinstance(v, str):
            return v
        entries = [o.strip() for o in v.split(",") if o.strip() and "*" not in o]
        return entries[0] if entries else cls.model_fields["frontend_url"].default

    # Superadmin. The user who registers with this email becomes the
    # superuser (global jobs, etc.). Empty disables the bootstrap.
    superadmin_email: str = ""

    # Auth methods: registration kill-switch and password kill-switch (SSO-only mode).
    auth_allow_registration: bool = True
    auth_password_enabled: bool = True
    # Generic OIDC/OAuth2 providers as a JSON list. Each entry:
    # {id, display_name?, discovery_url?, issuer?, authorize_url?, token_url?,
    #  userinfo_url?, jwks_uri?, client_id, client_secret, scopes?}.
    # discovery_url (or issuer + /.well-known/openid-configuration) covers
    # Google/Microsoft Entra/Okta/GitLab; explicit endpoint URLs cover
    # non-OIDC providers like GitHub. Secrets come from env, never committed.
    # issuer is pinned when set: a discovery document that names a different
    # one fails the login, so the value has to track the IdP's issuer.
    oauth_providers: str = ""

    # Auth brute-force protection: failures allowed per (IP, account) per window.
    auth_rate_limit_max_attempts: int = 10
    auth_rate_limit_window_seconds: int = 300
    # Single-workspace mode. When true, the first login/register creates the
    # one shared workspace (owned by whoever arrives first, normally the
    # superadmin) and every later login/register auto-joins it as
    # single_workspace_default_role. Creating a second workspace and deleting
    # the workspace are rejected; the sidebar switcher and the delete
    # danger-zone are hidden.
    single_workspace: bool = False
    # Role given to users who auto-join the single workspace: any of its
    # system or custom role names. An unknown or blank name falls back to
    # viewer (SINGLE_WORKSPACE_DEFAULT_ROLE=editor).
    single_workspace_default_role: str = "viewer"

    # Scheduled jobs
    jobs_scheduler_tick_seconds: float = 10.0
    jobs_default_timeout_seconds: int = 600
    jobs_run_retention: int = 1000  # per definition; pruned by scheduler housekeeping

    # Retention cleanup (days; enforced by the system.retention_cleanup job).
    # audit_log_retention_days=0 keeps audit entries forever (compliance trail).
    jobs_log_retention_days: int = Field(default=90, ge=0)
    notifications_retention_days: int = Field(default=90, ge=0)
    audit_log_retention_days: int = Field(default=0, ge=0)
    # Days a revoked or expired API key is kept before the apikeys.cleanup job
    # hard-deletes it. 0 disables deletion.
    api_key_retention_days: int = Field(default=30, ge=0)

    @property
    def database_url_sqlite(self) -> bool:
        return self.resolved_database_url.startswith("sqlite")

    @property
    def resolved_database_url(self) -> str:
        """Effective DB URL: explicit DATABASE_URL, USE_SQLITE file, or embedded postgres."""
        if self.database_url:
            return self.database_url
        if self.use_sqlite:
            return f"sqlite+aiosqlite:///{Path(__file__).resolve().parents[1] / 'dev.db'}"
        from src.db.embedded import embedded_uri

        return embedded_uri()

    @property
    def fernet_key_list(self) -> list[str]:
        return [k.strip() for k in self.fernet_keys.split(",") if k.strip()]

    @property
    def refresh_cookie_secure_effective(self) -> bool:
        if self.refresh_cookie_secure is not None:
            return self.refresh_cookie_secure
        # Dev and tests serve plain http:// — a Secure cookie would never
        # store. Production-like envs default to Secure.
        return self.environment not in ("development", "test")

    @property
    def _cors_origin_entries(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def cors_origin_list(self) -> list[str]:
        return [o for o in self._cors_origin_entries if "*" not in o]

    @property
    def cors_origin_regex(self) -> str | None:
        """Origin regex from the wildcard CORS_ORIGINS entries; None when there are none.

        Starlette fullmatches this against the Origin header. Every other part
        of the entry is escaped, so only `*` stays open (it never matches a
        `/`, so a pattern cannot span past the origin); an entry without a
        scheme matches http and https, and the port is optional because an
        Origin rarely carries it."""
        patterns = []
        for entry in self._cors_origin_entries:
            if "*" not in entry:
                continue
            scheme, has_scheme, host = entry.partition("://")
            if not has_scheme:
                scheme, host = "", entry
            patterns.append(
                f"{re.escape(scheme) if has_scheme else 'https?'}://"
                f"{re.escape(host).replace(re.escape('*'), '[^/]+')}(?::[0-9]+)?"
            )
        return "|".join(patterns) or None

    @property
    def oauth_provider_list(self) -> list[dict]:
        """Parsed OAUTH_PROVIDERS JSON (empty list when unset or invalid)."""
        import json as _json

        raw = (self.oauth_providers or "").strip()
        if not raw:
            return []
        try:
            parsed = _json.loads(raw)
        except ValueError:
            return []
        return parsed if isinstance(parsed, list) else []


settings = Settings()
