from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv


def normalize_database_url(url: str) -> str:
    # Render/Heroku hand out postgres:// URLs; SQLAlchemy wants an explicit driver.
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


@dataclass
class Settings:
    database_url: str = "sqlite:///./campus_inbox.db"
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.5-flash"
    cors_origins: list[str] = field(default_factory=lambda: ["http://localhost:5173"])
    # If set, every endpoint except /health requires "Authorization: Bearer <app_token>".
    app_token: str | None = None
    # Run Alembic migrations on startup (in-memory SQLite always uses create_all instead).
    migrate_on_startup: bool = True
    # Read-only IMAP sync. For Gmail use imap.gmail.com and an app password.
    imap_host: str | None = None
    imap_user: str | None = None
    imap_password: str | None = None
    imap_mailbox: str = "INBOX"
    imap_sender_filter: str | None = None  # e.g. your placement cell's address

    @property
    def imap_configured(self) -> bool:
        return bool(self.imap_host and self.imap_user and self.imap_password)

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        env = os.getenv
        return cls(
            database_url=normalize_database_url(env("DATABASE_URL", cls.database_url)),
            gemini_api_key=env("GEMINI_API_KEY") or None,
            gemini_model=env("GEMINI_MODEL") or cls.gemini_model,
            cors_origins=[o.strip() for o in env("CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()],
            app_token=env("APP_TOKEN") or None,
            migrate_on_startup=env("MIGRATE_ON_STARTUP", "true").lower() != "false",
            imap_host=env("IMAP_HOST") or None,
            imap_user=env("IMAP_USER") or None,
            imap_password=env("IMAP_PASSWORD") or None,
            imap_mailbox=env("IMAP_MAILBOX") or cls.imap_mailbox,
            imap_sender_filter=env("IMAP_SENDER_FILTER") or None,
        )
