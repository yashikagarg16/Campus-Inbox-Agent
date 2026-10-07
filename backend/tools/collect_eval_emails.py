"""Collect real placement emails over read-only IMAP for the labeled eval set.

Step 1, look before reading anything (headers only: sender, subject, date):
    python -m tools.collect_eval_emails senders --since 2025-07-01

Step 2, download only the senders you confirmed, redacted, into the gitignored private folder:
    python -m tools.collect_eval_emails download --from placement@college.edu --since 2025-07-01

Writes eval/data/private/candidates.jsonl (one email per line, unlabeled). Re-running appends
only emails that aren't already there. Uses IMAP_HOST / IMAP_USER / IMAP_PASSWORD from .env.
Nothing is sent anywhere else, and no LLM is called.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from datetime import date
from email.utils import parseaddr
from pathlib import Path

from app.config import Settings
from app.imap_sync import fetch_headers, fetch_raw_messages
from app.parsing import parse_eml

from .redact import redact

PRIVATE_DIR = Path(__file__).resolve().parent.parent / "eval" / "data" / "private"
DEFAULT_KEYWORDS = ["placement", "internship", "CGPA", "eligibility", "eligible", "batch", "hiring",
                    "recruitment", "drive", "registration", "apply"]


def list_senders(headers) -> list[tuple[str, int, list[str]]]:
    counts: Counter = Counter()
    subjects: dict[str, list[str]] = defaultdict(list)
    for h in headers:
        addr = parseaddr(h["from"])[1].lower() or h["from"]
        counts[addr] += 1
        if len(subjects[addr]) < 3:
            subjects[addr].append(h["subject"])
    return [(addr, n, subjects[addr]) for addr, n in counts.most_common()]


def _hash(text: str) -> str:
    return hashlib.sha256(" ".join(text.split()).lower().encode()).hexdigest()


def collect(raw_messages, names: list[str], existing: list[dict]) -> list[dict]:
    """Turn raw messages into redacted, de-duplicated eval records (unlabeled)."""
    seen = {r.get("content_hash") for r in existing}
    next_id = len(existing) + 1
    new = []
    for raw in raw_messages:
        parsed = parse_eml(raw)
        if len(parsed.body) < 40:
            continue
        text = redact(parsed.body, names)
        digest = _hash(text)
        if digest in seen:
            continue
        seen.add(digest)
        new.append({
            "id": f"real-{next_id:03d}",
            "received_at": parsed.received_at.isoformat(timespec="minutes") if parsed.received_at else None,
            "subject": redact(parsed.subject or "", names),
            "text": text,
            "content_hash": digest,
            "label_status": "unlabeled",
            "expected_opportunities": [],
        })
        next_id += 1
    return new


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("senders", "download"):
        p = sub.add_parser(name)
        p.add_argument("--since", type=date.fromisoformat, default=date(date.today().year - 1, 7, 1))
        p.add_argument("--keyword", action="append", help="search words (default: placement-related words)")
    sub.choices["senders"].add_argument("--limit", type=int, default=500)
    dl = sub.choices["download"]
    dl.add_argument("--from", dest="senders", action="append", required=True, help="confirmed sender address")
    dl.add_argument("--limit", type=int, default=150, help="max emails per sender")
    dl.add_argument("--names", nargs="*", default=[], help="names to redact, e.g. your own")
    dl.add_argument("--all-mail", action="store_true", help="don't require placement keywords, just the sender")
    args = ap.parse_args()

    s = Settings.from_env()
    if not s.imap_configured:
        sys.exit("Set IMAP_HOST, IMAP_USER and IMAP_PASSWORD in backend/.env first.")
    keywords = args.keyword or DEFAULT_KEYWORDS

    if args.cmd == "senders":
        headers = fetch_headers(s.imap_host, s.imap_user, s.imap_password, args.since, mailbox=s.imap_mailbox,
                                keywords=keywords, limit=args.limit)
        rows = list_senders(headers)
        print(f"{sum(n for _, n, _ in rows)} matching emails since {args.since}, by sender:\n")
        for addr, n, subjects in rows:
            print(f"{n:4d}  {addr}")
            for subj in subjects:
                print(f"        - {subj[:90]}")
        return

    PRIVATE_DIR.mkdir(parents=True, exist_ok=True)
    out = PRIVATE_DIR / "candidates.jsonl"
    existing = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines() if l.strip()] if out.exists() else []
    names = [*args.names, s.imap_user.split("@")[0]]
    added = []
    for sender in args.senders:
        raws = fetch_raw_messages(s.imap_host, s.imap_user, s.imap_password, args.since, mailbox=s.imap_mailbox,
                                  sender=sender, limit=args.limit, keywords=None if args.all_mail else keywords)
        added += collect(raws, names, existing + added)
    with out.open("a", encoding="utf-8") as f:
        for rec in added:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"Added {len(added)} emails to {out} ({len(existing) + len(added)} total). Read them before labeling: "
          "redaction catches emails, phone numbers and the names you passed, not everything.")


if __name__ == "__main__":
    main()
