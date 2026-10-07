"""Collect real placement emails, read-only, for the labeled eval set.

Step 1, look before reading anything (headers only: sender, subject, date):
    python -m tools.collect_eval_emails senders --since 2025-07-01

Step 2, download only the senders you confirmed, redacted, into the gitignored private folder:
    python -m tools.collect_eval_emails download --from placement@college.edu --since 2025-07-01

Or, with no mailbox access, import .eml files you downloaded yourself:
    python -m tools.collect_eval_emails import-files --dir path/to/emls

The mailbox is Outlook / Microsoft 365 via Graph if MS_CLIENT_ID is set, otherwise IMAP
(IMAP_HOST / IMAP_USER / IMAP_PASSWORD). Writes eval/data/private/candidates.jsonl (one email
per line, unlabeled); re-running appends only new emails. No LLM is called.
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
from app.graph_mail import GraphMail, get_token
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
    files = sub.add_parser("import-files")
    files.add_argument("--dir", type=Path, required=True)
    files.add_argument("--names", nargs="*", default=[], help="names to redact, e.g. your own")
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
    if args.cmd == "import-files":
        raws = [p.read_bytes() for p in sorted(args.dir.glob("*.eml"))]
        if not raws:
            sys.exit(f"No .eml files in {args.dir}")
        _save(lambda existing: collect(raws, args.names, existing))
        return

    keywords = args.keyword or DEFAULT_KEYWORDS
    if s.ms_client_id:
        mail = GraphMail(get_token(s.ms_client_id, s.ms_tenant, show=lambda m: print(m, flush=True)))

        def fetch_hdrs(since, limit):
            return mail.headers(since, keywords=keywords, limit=limit)

        def fetch_raw(since, sender, limit, kw):
            return mail.raw_messages(since, sender=sender, keywords=kw, limit=limit)

        own_names = mail.identity()
    elif s.imap_configured:
        def fetch_hdrs(since, limit):
            return fetch_headers(s.imap_host, s.imap_user, s.imap_password, since, mailbox=s.imap_mailbox,
                                 keywords=keywords, limit=limit)

        def fetch_raw(since, sender, limit, kw):
            return fetch_raw_messages(s.imap_host, s.imap_user, s.imap_password, since, mailbox=s.imap_mailbox,
                                      sender=sender, limit=limit, keywords=kw)

        own_names = [s.imap_user.split("@")[0]]
    else:
        sys.exit("Set MS_CLIENT_ID (Outlook) or IMAP_HOST/IMAP_USER/IMAP_PASSWORD in backend/.env first, "
                 "or use import-files.")

    if args.cmd == "senders":
        rows = list_senders(fetch_hdrs(args.since, args.limit))
        print(f"{sum(n for _, n, _ in rows)} matching emails since {args.since}, by sender:\n")
        for addr, n, subjects in rows:
            print(f"{n:4d}  {addr}")
            for subj in subjects:
                print(f"        - {subj[:90]}")
        return

    names = [*args.names, *own_names]

    def gather(existing: list[dict]) -> list[dict]:
        added: list[dict] = []
        for sender in args.senders:
            raws = fetch_raw(args.since, sender, args.limit, None if args.all_mail else keywords)
            added += collect(raws, names, existing + added)
        return added

    _save(gather)


def _save(gather) -> None:
    PRIVATE_DIR.mkdir(parents=True, exist_ok=True)
    out = PRIVATE_DIR / "candidates.jsonl"
    existing = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines() if l.strip()] if out.exists() else []
    added = gather(existing)
    with out.open("a", encoding="utf-8") as f:
        for rec in added:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"Added {len(added)} emails to {out} ({len(existing) + len(added)} total). Read them before labeling: "
          "redaction catches emails, phone numbers and the names you passed, not everything.")


if __name__ == "__main__":
    main()
