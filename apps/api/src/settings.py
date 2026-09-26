import os
import re
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.email.base import EmailDriver  # noqa: E402  (base has no settings import)
from src.events.subjects import EventBusDriver


def slugify(value: str) -> str:
    """Lowercase kebab identifier, safe for paths, NATS names and resource names."""
    return re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")


# The env-file location is fixed at class-creation time, so it cannot come from
# a field. Both it and the app_slug default follow the process env; a project
# .env is still read first and wins.
APP_SLUG = slugify(os.environ.get("APP_SLUG", "saas-template")) or "app"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", os.path.expanduser(f"~/.config/{APP_SLUG}/.env")),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: str = "development"
    # Human-facing product name: OpenAPI title, TOTP issuer, GET / and /healthz.
    app_name: str = "saas-template-api"
    # Machine identifier for everything that must be stable and lowercase:
    # NATS stream/queue group, the user config dir, the embedded-DB data dir.
    app_slug: str = APP_SLUG
    debug: bool = False

    @field_validator("app_slug", mode="after")
    @classmethod
    def _app_slug_is_kebab(cls, v: str) -> str:
        # An empty APP_SLUG must not yield "" (paths like ~/.config//, an empty
        # NATS stream name); "app" is the neutral floor.
        return slugify(v) or "app"

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
    # The default is a historical name; changing it invalidates every existing
    # session, so renaming is opt-in (REFRESH_COOKIE_NAME) rather than derived
    # from app_slug.
    # refresh_cookie_secure=None (default) → Secure unless development.
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

    # CORS / frontend (comma-separated)
    cors_origins: str = "http://localhost:5173"
    frontend_url: str = "http://localhost:5173"

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
    oauth_providers: str = ""

    # Auth brute-force protection: failures allowed per (IP, account) per window.
    auth_rate_limit_max_attempts: int = 10
    auth_rate_limit_window_seconds: int = 300
    # Single-workspace mode. When true, the first login/register creates the
    # one shared workspace (owned by whoever arrives first, normally the
    # superadmin) and every later login/register auto-joins it as viewer.
    # Creating a second workspace and deleting the workspace are rejected;
    # the sidebar switcher and the delete danger-zone are hidden.
    single_workspace: bool = False

    # Scheduled jobs
    jobs_scheduler_tick_seconds: float = 10.0
    jobs_default_timeout_seconds: int = 600
    jobs_run_retention: int = 1000  # per definition; pruned by scheduler housekeeping

    # Retention cleanup (days; enforced by the system.retention_cleanup job).
    # audit_log_retention_days=0 keeps audit entries forever (compliance trail).
    jobs_log_retention_days: int = Field(default=90, ge=0)
    notifications_retention_days: int = Field(default=90, ge=0)
    audit_log_retention_days: int = Field(default=0, ge=0)

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
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

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
