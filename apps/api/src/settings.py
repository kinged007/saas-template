import os
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
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
