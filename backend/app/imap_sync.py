"""Read-only mailbox access over IMAP.

Read-only is enforced two ways: the mailbox is SELECTed with readonly=True (the
server rejects any change), and messages are fetched with BODY.PEEK so they are
not even marked as read. Nothing here can send, delete or move mail.
"""

from __future__ import annotations

import imaplib
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


def fetch_raw_messages(
    host: str,
    user: str,
    password: str,
    since: date,
    mailbox: str = "INBOX",
    sender: str | None = None,
    limit: int = 25,
    connect: Callable[[str], IMAPConnection] = imaplib.IMAP4_SSL,
) -> Iterator[bytes]:
    """Yield raw RFC 822 messages received on or after `since`, newest `limit` only."""
    conn = connect(host)
    try:
        conn.login(user, password)
        typ, _ = conn.select(_quote(mailbox), readonly=True)
        if typ != "OK":
            raise RuntimeError(f"Couldn't open mailbox {mailbox!r}")
        criteria = ["SINCE", since.strftime("%d-%b-%Y")]
        if sender:
            criteria += ["FROM", _quote(sender)]
        typ, data = conn.search(None, *criteria)
        if typ != "OK":
            raise RuntimeError("IMAP search failed")
        ids = data[0].split()[-limit:] if data and data[0] else []
        for msg_id in ids:
            typ, parts = conn.fetch(msg_id, "(BODY.PEEK[])")
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
