"""Read-only mailbox access over IMAP.

Read-only is enforced two ways: the mailbox is SELECTed with readonly=True (the
server rejects any change), and messages are fetched with BODY.PEEK so they are
not even marked as read. Nothing here can send, delete or move mail.
"""

from __future__ import annotations

import email
import imaplib
from email import policy
from datetime import date
from typing import Callable, Iterator, Protocol


class IMAPConnection(Protocol):
    def login(self, user: str, password: str): ...
    def select(self, mailbox: str = "INBOX", readonly: bool = False): ...
    def search(self, charset, *criteria): ...
    def fetch(self, message_set, message_parts): ...
    def logout(self): ...


def _quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def build_criteria(host: str, since: date, sender: str | None = None,
                   keywords: list[str] | None = None) -> list[str]:
    """IMAP SEARCH criteria. On Gmail, keyword searches use Gmail's own search syntax."""
    if keywords and "gmail" in host.lower():
        raw = f"after:{since:%Y/%m/%d} ({' OR '.join(keywords)})"
        if sender:
            raw += f" from:{sender}"
        return ["X-GM-RAW", _quote(raw)]
    criteria = ["SINCE", since.strftime("%d-%b-%Y")]
    if sender:
        criteria += ["FROM", _quote(sender)]
    if keywords:
        for keyword in keywords[:-1]:
            criteria += ["OR", "TEXT", _quote(keyword)]
        criteria += ["TEXT", _quote(keywords[-1])]
    return criteria


def _fetch(host, user, password, mailbox, criteria, limit, parts_spec, connect) -> Iterator[bytes]:
    conn = connect(host)
    try:
        conn.login(user, password)
        typ, _ = conn.select(_quote(mailbox), readonly=True)
        if typ != "OK":
            raise RuntimeError(f"Couldn't open mailbox {mailbox!r}")
        typ, data = conn.search(None, *criteria)
        if typ != "OK":
            raise RuntimeError("IMAP search failed")
        ids = data[0].split()[-limit:] if data and data[0] else []
        for msg_id in ids:
            typ, parts = conn.fetch(msg_id, parts_spec)
            if typ != "OK":
                continue
            for part in parts:
                if isinstance(part, tuple) and len(part) == 2:
                    yield part[1]
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def fetch_raw_messages(
    host: str,
    user: str,
    password: str,
    since: date,
    mailbox: str = "INBOX",
    sender: str | None = None,
    limit: int = 25,
    keywords: list[str] | None = None,
    connect: Callable[[str], IMAPConnection] = imaplib.IMAP4_SSL,
) -> Iterator[bytes]:
    """Yield raw RFC 822 messages received on or after `since`, newest `limit` only."""
    criteria = build_criteria(host, since, sender, keywords)
    yield from _fetch(host, user, password, mailbox, criteria, limit, "(BODY.PEEK[])", connect)


def fetch_headers(
    host: str,
    user: str,
    password: str,
    since: date,
    mailbox: str = "INBOX",
    sender: str | None = None,
    limit: int = 500,
    keywords: list[str] | None = None,
    connect: Callable[[str], IMAPConnection] = imaplib.IMAP4_SSL,
) -> Iterator[dict[str, str]]:
    """Yield only From/Subject/Date of matching messages, so senders can be checked before any body is read."""
    criteria = build_criteria(host, since, sender, keywords)
    spec = "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])"
    for raw in _fetch(host, user, password, mailbox, criteria, limit, spec, connect):
        msg = email.message_from_bytes(raw, policy=policy.default)
        yield {"from": str(msg["from"] or ""), "subject": str(msg["subject"] or ""), "date": str(msg["date"] or "")}
