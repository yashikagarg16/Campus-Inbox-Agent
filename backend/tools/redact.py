"""Redact personal data from email text before it goes into a test set or a demo.

    python -m tools.redact input.txt > redacted.txt
    python -m tools.redact input.txt --names "Riya Sharma" "Dr. Rao"

Catches email addresses, phone numbers and any names you pass. Always read the
output yourself before committing it: patterns can't catch everything.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE_RE = re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}(?!\d)")


def redact(text: str, names: list[str] | None = None) -> str:
    text = EMAIL_RE.sub("[EMAIL]", text)
    text = PHONE_RE.sub("[PHONE]", text)
    for name in names or []:
        text = re.sub(re.escape(name), "[NAME]", text, flags=re.IGNORECASE)
    return text


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", type=Path)
    ap.add_argument("--names", nargs="*", default=[])
    args = ap.parse_args()
    sys.stdout.write(redact(args.path.read_text(encoding="utf-8"), args.names))


if __name__ == "__main__":
    main()
