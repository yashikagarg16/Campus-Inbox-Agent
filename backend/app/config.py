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
    gemini_model: str = "gemini-3.8-flash"
    # "low" | "medium" | "high"; unset uses the model's default (medium).
    gemini_thinking_level: str | None = None
    # Used when the main model stays overloaded after retries, e.g. gemini-3.5-flash-lite.
    gemini_fallback_model: str | None = None
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
    # Read-only Microsoft 365 / Outlook via Microsoft Graph (IMAP passwords don't work there).
    # The client ID comes from an app registration; see README "Outlook / Microsoft 365".
    ms_client_id: str | None = None
    ms_tenant: str = "organizations"

    def gemini_client(self):
        from .extractor import GeminiClient

        return GeminiClient(self.gemini_api_key, self.gemini_model, self.gemini_thinking_level,
                            fallback_model=self.gemini_fallback_model)

    @property
    def imap_configured(self) -> bool:
        return bool(self.imap_host and self.imap_user and self.imap_password)

    @property
    def mail_source(self) -> str | None:
        """Which inbox sync is set up: "graph" (Outlook), "imap", or None."""
        if self.ms_client_id:
            return "graph"
        return "imap" if self.imap_configured else None

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        env = os.getenv
        return cls(
            database_url=normalize_database_url(env("DATABASE_URL", cls.database_url)),
            gemini_api_key=env("GEMINI_API_KEY") or None,
            gemini_model=env("GEMINI_MODEL") or cls.gemini_model,
            gemini_thinking_level=env("GEMINI_THINKING_LEVEL") or None,
            gemini_fallback_model=env("GEMINI_FALLBACK_MODEL") or None,
            cors_origins=[o.strip() for o in env("CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()],
            app_token=env("APP_TOKEN") or None,
            migrate_on_startup=env("MIGRATE_ON_STARTUP", "true").lower() != "false",
            imap_host=env("IMAP_HOST") or None,
            imap_user=env("IMAP_USER") or None,
            imap_password=env("IMAP_PASSWORD") or None,
            imap_mailbox=env("IMAP_MAILBOX") or cls.imap_mailbox,
            imap_sender_filter=env("IMAP_SENDER_FILTER") or None,
            ms_client_id=env("MS_CLIENT_ID") or None,
            ms_tenant=env("MS_TENANT") or cls.ms_tenant,
        )
