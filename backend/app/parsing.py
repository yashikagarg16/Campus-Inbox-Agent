"""Step 1: turn pasted text or an .eml file into clean plain text."""

from __future__ import annotations

import email
import re
from dataclasses import dataclass
from datetime import datetime
from email import policy
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser

from .schemas import to_local_naive

_BLOCK_TAGS = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "table", "ul", "ol"}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0
        self._href: str | None = None

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")
        elif tag == "a":
            self._href = dict(attrs).get("href")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")
        elif tag == "a" and self._href:
            # Form links are often hidden behind "click here"; keep the URL visible.
            if self._href.startswith("http"):
                self.parts.append(f" ({self._href})")
            self._href = None

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()
    return "".join(parser.parts)


def clean_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[​‌‍﻿]", "", text)
    lines = [line.rstrip() for line in text.split("\n") if not line.lstrip().startswith(">")]
    text = "\n".join(lines)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


@dataclass
class ParsedEmail:
    body: str
    subject: str | None = None
    sender: str | None = None
    received_at: datetime | None = None
    message_id: str | None = None


def parse_eml(data: bytes) -> ParsedEmail:
    msg = email.message_from_bytes(data, policy=policy.default)
    part = msg.get_body(preferencelist=("plain", "html"))
    body = ""
    if part is not None:
        body = part.get_content()
        if part.get_content_type() == "text/html":
            body = html_to_text(body)
    received_at = None
    if msg["date"]:
        try:
            received_at = to_local_naive(parsedate_to_datetime(str(msg["date"])))
        except (TypeError, ValueError):
            received_at = None
    return ParsedEmail(
        body=clean_text(body),
        subject=str(msg["subject"]) if msg["subject"] else None,
        sender=str(msg["from"]) if msg["from"] else None,
        received_at=received_at,
        message_id=str(msg["message-id"]).strip() if msg["message-id"] else None,
    )
