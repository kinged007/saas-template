import os
import re
from pathlib import Path

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.email.base import EmailDriver  # noqa: E402  (base has no settings import)
from src.events.subjects import EventBusDriver

DEFAULT_APP_NAME = "SaaS Template"
DEFAULT_APP_SLUG = "saas-template"


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:63].rstrip("-")
    return slug or "app"


def _default_app_slug() -> str:
    value = os.environ.get("APP_SLUG") or os.environ.get("APP_NAME")
    if not value:
        return DEFAULT_APP_SLUG
    slug = _slugify(value)
    return slug.removesuffix("-api") or "app"


_CONFIG_ENV_FILE = Path.home() / ".config" / _default_app_slug() / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", _CONFIG_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: str = "development"
    app_name: str = Field(default=DEFAULT_APP_NAME, min_length=1)
    app_slug: str = Field(default_factory=_default_app_slug)
    debug: bool = False

    # Database. Empty → embedded PostgreSQL (pgserver; dev, no external deps).
    # Set DATABASE_URL (e.g. managed postgres) to override in production.
    database_url: str = ""

    # USE_SQLITE=1 → file DB at apps/api/dev.db instead of embedded postgres.
    # Per-checkout file, so multiple worktrees don't share a server or data
    # dir; startup is instant (no postgres boot). Explicit DATABASE_URL wins.
    use_sqlite: bool = False
    embedded_db_dir: str = ""

    @field_validator("app_name", mode="before")
    @classmethod
    def _strip_app_name(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("app_slug")
    @classmethod
    def _validate_app_slug(cls, value: str) -> str:
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", value):
            raise ValueError("app_slug must be a lowercase DNS-style identifier")
        return value

    @field_validator("nats_stream_name", "nats_consumer_prefix")
    @classmethod
    def _validate_nats_name(cls, value: str) -> str:
        value = value.strip()
        if value and not re.fullmatch(r"[A-Za-z0-9_-]+", value):
            raise ValueError(
                "NATS names may contain only letters, numbers, underscores, and hyphens"
            )
        return value

    @model_validator(mode="after")
    def _derive_identifiers(self):
        if "app_slug" not in self.model_fields_set:
            self.app_slug = _slugify(self.app_name).removesuffix("-api") or "app"
        if "refresh_cookie_name" not in self.model_fields_set:
            self.refresh_cookie_name = (
                "st_refresh"
                if self.app_slug == DEFAULT_APP_SLUG
                else f"{self.app_slug.replace('-', '_')}_refresh"
            )
        return self

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
    nats_stream_name: str = ""
    nats_consumer_prefix: str = ""

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
    seed_email_domain: str = "example.com"
    seed_workspace_names: str = "Acme Corp,Globex"

    @field_validator("refresh_cookie_name")
    @classmethod
    def _validate_refresh_cookie_name(cls, value: str) -> str:
        if not re.fullmatch(r"[!#$%&'*+\-.^_`|~0-9A-Za-z]+", value):
            raise ValueError("refresh_cookie_name must be a valid HTTP cookie name")
        return value

    @field_validator("seed_email_domain", "seed_workspace_names")
    @classmethod
    def _strip_nonempty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value cannot be empty")
        return value

    @field_validator("seed_workspace_names")
    @classmethod
    def _validate_seed_workspace_names(cls, value: str) -> str:
        names = [name.strip() for name in value.split(",")]
        if len(names) != 2 or not all(names):
            raise ValueError("seed_workspace_names must contain exactly two comma-separated names")
        if len({_slugify(name) for name in names}) != 2:
            raise ValueError("seed workspace names must produce different slugs")
        return ", ".join(names)

    @property
    def seed_workspace_specs(self) -> list[dict[str, str]]:
        return [
            {
                "name": name,
                "slug": _slugify(name),
                "description": "Demo workspace" if index == 0 else "Second demo workspace",
            }
            for index, name in enumerate(
                name.strip() for name in self.seed_workspace_names.split(",")
            )
        ]

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
    def api_name(self) -> str:
        return f"{self.app_name} API"

    @property
    def service_name(self) -> str:
        return f"{self.app_slug}-api"

    @property
    def nats_stream_name_effective(self) -> str:
        return (self.nats_stream_name.strip() or self.app_slug.replace("-", "_")).upper()

    @property
    def nats_consumer_prefix_effective(self) -> str:
        explicit = self.nats_consumer_prefix.strip()
        if explicit:
            return explicit
        return "".join(part[0] for part in self.app_slug.split("-") if part) or "app"

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
