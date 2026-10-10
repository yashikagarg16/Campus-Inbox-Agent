"""Pull recent placement emails over read-only IMAP and run them through the pipeline.

    python -m tools.fetch_imap --days 7 --limit 25

Needs IMAP_HOST, IMAP_USER, IMAP_PASSWORD (and optionally IMAP_SENDER_FILTER) plus
GEMINI_API_KEY in the environment or .env. For Gmail: IMAP_HOST=imap.gmail.com and an
app password (Google Account > Security > App passwords).
"""

from __future__ import annotations

import argparse
import sys
from datetime import timedelta

from app.config import Settings
from app.models import make_sessionmaker
from app.schemas import local_now
from app.users import LOCAL_EMAIL, ensure_user
from app.service import sync_imap


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--limit", type=int, default=25)
    args = ap.parse_args()

    settings = Settings.from_env()
    if not settings.imap_configured:
        sys.exit("Set IMAP_HOST, IMAP_USER and IMAP_PASSWORD first.")
    if not settings.gemini_api_key:
        sys.exit("Set GEMINI_API_KEY first.")

    Session = make_sessionmaker(settings.database_url, migrate=settings.migrate_on_startup)
    since = (local_now() - timedelta(days=args.days)).date()
    with Session() as session:
        owner = ensure_user(session, settings.admin_email or LOCAL_EMAIL, "owner" if settings.admin_email else "local")
        result = sync_imap(session, settings.gemini_client(), settings, since, limit=args.limit, user_id=owner.id)
    print(f"fetched {result.fetched}, new {result.new}, duplicates {result.duplicates}, failed {result.failed}")


if __name__ == "__main__":
    main()
