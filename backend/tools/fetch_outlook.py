"""Sign in to Outlook / Microsoft 365 (read-only) and pull recent placement emails into the app.

    python -m tools.fetch_outlook --sign-in          # one-time: prints a code for microsoft.com/devicelogin
    python -m tools.fetch_outlook --days 7           # sync the last 7 days into the app's database

Needs MS_CLIENT_ID (and GEMINI_API_KEY for syncing) in backend/.env. After the first sign-in the
web app's "Check inbox" button works too, using the cached sign-in.
"""

from __future__ import annotations

import argparse
import sys
from datetime import timedelta

from app.config import Settings
from app.extractor import GeminiClient
from app.graph_mail import GraphMail, get_token
from app.models import make_sessionmaker
from app.schemas import local_now
from app.service import sync_messages


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sign-in", action="store_true", help="only sign in and check access, don't sync")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--limit", type=int, default=25)
    args = ap.parse_args()

    settings = Settings.from_env()
    if not settings.ms_client_id:
        sys.exit("Set MS_CLIENT_ID in backend/.env first (see README, 'Outlook / Microsoft 365').")
    token = get_token(settings.ms_client_id, settings.ms_tenant, show=lambda m: print(m, flush=True))
    if args.sign_in:
        since = (local_now() - timedelta(days=30)).date()
        n = sum(1 for _ in GraphMail(token).headers(since, limit=5))
        print(f"Signed in. Read access works ({n} recent message headers visible). Nothing was changed.")
        return
    if not settings.gemini_api_key:
        sys.exit("Set GEMINI_API_KEY first.")

    Session = make_sessionmaker(settings.database_url, migrate=settings.migrate_on_startup)
    since = (local_now() - timedelta(days=args.days)).date()
    messages = GraphMail(token).raw_messages(since, sender=settings.imap_sender_filter, limit=args.limit)
    llm = GeminiClient(settings.gemini_api_key, settings.gemini_model, settings.gemini_thinking_level)
    with Session() as session:
        r = sync_messages(session, llm, messages, since, "outlook")
    print(f"fetched {r.fetched}, new {r.new}, duplicates {r.duplicates}, failed {r.failed}")


if __name__ == "__main__":
    main()
