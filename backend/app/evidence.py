"""Evidence guard: reject any extracted field whose proof is not really in the email.

Two checks per field:
1. The evidence quote must appear in the email (after normalising whitespace,
   case, smart quotes and dashes).
2. The value must be grounded in its own quote: a CGPA of 8.0 needs "8.0" in the
   quote, batch 2027 needs 2027 (or a range covering it), and so on.

A field that fails either check is blanked and reported as a FieldIssue. The
rule engine turns issues on eligibility fields into "needs review".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from .schemas import EVIDENCED_FIELDS, Evidenced, Extraction, FieldIssue

MIN_EVIDENCE_CHARS = 6

_CHAR_MAP = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"',
    "–": "-", "—": "-", "−": "-",
    " ": " ", " ": " ", " ": " ",
}
# Formatting characters an LLM tends to drop when quoting.
_DROP = set("​‌‍﻿*_•▪●◦")
_EDGE = " .,;:!?'\"-()[]…"


def _normalize(text: str) -> tuple[str, list[int]]:
    """Normalise text for matching; also return each output char's index in `text`."""
    chars: list[str] = []
    index: list[int] = []
    prev_space = True
    for i, ch in enumerate(text):
        if ch in _DROP:
            continue
        ch = _CHAR_MAP.get(ch, ch)
        if ch.isspace():
            if not prev_space:
                chars.append(" ")
                index.append(i)
                prev_space = True
            continue
        for c in ch.lower():
            chars.append(c)
            index.append(i)
        prev_space = False
    if chars and chars[-1] == " ":
        chars.pop()
        index.pop()
    return "".join(chars), index


def normalize(text: str) -> str:
    return _normalize(text)[0]


def find_span(text: str, evidence: str | None) -> tuple[int, int] | None:
    """Return (start, end) of `evidence` inside `text`, or None if it isn't there."""
    if not evidence:
        return None
    needle = normalize(evidence).strip(_EDGE)
    if len(needle) < MIN_EVIDENCE_CHARS:
        return None
    haystack, index = _normalize(text)
    pos = haystack.find(needle)
    if pos == -1:
        return None
    return index[pos], index[pos + len(needle) - 1] + 1


_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
_YEAR_RE = re.compile(r"\b(20\d{2})\b")
_YEAR_RANGE_RE = re.compile(r"\b(20\d{2})\s*(?:-|to|till|until|through)\s*(20\d{2}|\d{2})\b")
_SHORT_YEAR_RE = re.compile(r"'(\d{2})\b")
_ZERO_WORDS_RE = re.compile(r"\b(no|zero|nil|none|without|not have any|not having any)\b")


def numbers_in(text: str) -> list[float]:
    return [float(n) for n in _NUMBER_RE.findall(text)]


def years_in(text: str) -> set[int]:
    text = normalize(text)
    years = {int(y) for y in _YEAR_RE.findall(text)}
    years |= {2000 + int(y) for y in _SHORT_YEAR_RE.findall(text)}
    for a, b in _YEAR_RANGE_RE.findall(text):
        start = int(a)
        end = int(b) if len(b) == 4 else start // 100 * 100 + int(b)
        if start <= end <= start + 10:
            years.update(range(start, end + 1))
    return years


def _has_number(value: float, evidence: str) -> bool:
    return any(abs(n - value) < 1e-6 for n in numbers_in(evidence))


_RELATIVE_DAYS = (("day after tomorrow", 2), ("tomorrow", 1), ("today", 0), ("tonight", 0), ("eod", 0))


def _relative_day(evidence: str) -> int | None:
    """Days after the received date that a relative deadline quote means, if it is one."""
    text = normalize(evidence)
    if _NUMBER_RE.search(re.sub(r"\d{1,2}(:\d{2})?\s*(am|pm)|\d{1,2}:\d{2}", "", text)):
        return None  # an explicit date is present; check that instead
    for phrase, days in _RELATIVE_DAYS:
        if re.search(rf"\b{phrase}\b", text):
            return days
    return None


def _clean_url(url: str) -> str:
    return url.strip().rstrip(").,;>]")


def _grounding_problem(name: str, value, evidence: str, text: str, received_at: datetime | None) -> str | None:
    if name in ("min_cgpa", "min_10th_percent", "min_12th_percent"):
        if not _has_number(value, evidence):
            return f"value {value} does not appear in its evidence quote"
    elif name == "max_active_backlogs":
        if not _has_number(value, evidence) and not (value == 0 and _ZERO_WORDS_RE.search(normalize(evidence))):
            return f"value {value} does not appear in its evidence quote"
    elif name == "batches":
        missing = sorted(set(value) - years_in(evidence))
        if missing:
            return f"batch year(s) {missing} do not appear in the evidence quote"
    elif name == "form_link":
        if _clean_url(value) not in text:
            return "link does not appear in the email"
    elif name == "deadline":
        relative = _relative_day(evidence)
        if relative is not None:
            if received_at is None:
                return "deadline is relative (today/tomorrow) but the received date is unknown"
            if (value.date() - received_at.date()).days != relative:
                return "deadline doesn't match the relative date in the quote"
        elif not _has_number(value.day, evidence):
            return f"deadline day ({value.day}) is not stated in the evidence quote"
        if received_at is not None and value.date() < received_at.date():
            return "deadline is earlier than the date the email was received (likely a wrong year)"
    return None


@dataclass
class GuardResult:
    extraction: Extraction
    issues: list[FieldIssue] = field(default_factory=list)
    spans: dict[str, tuple[int, int]] = field(default_factory=dict)


def guard(extraction: Extraction, email_text: str, received_at: datetime | None = None) -> GuardResult:
    """Return a copy of `extraction` with every unverifiable field blanked out."""
    cleaned = extraction.model_copy(deep=True)
    result = GuardResult(extraction=cleaned)

    for name in EVIDENCED_FIELDS:
        item: Evidenced = getattr(cleaned, name)
        if item.value is None:
            continue
        span = find_span(email_text, item.evidence)
        if span is None:
            problem = "evidence quote not found in the email"
        else:
            problem = _grounding_problem(name, item.value, item.evidence, email_text, received_at)
        if problem:
            value = item.value.isoformat() if isinstance(item.value, datetime) else item.value
            result.issues.append(FieldIssue(field=name, reason=problem, value=value, evidence=item.evidence))
            setattr(cleaned, name, type(item)())
        else:
            result.spans[name] = span

    kept = []
    for item in cleaned.other_criteria:
        span = find_span(email_text, item.evidence)
        if span is None:
            result.issues.append(FieldIssue(
                field="other_criteria", reason="evidence quote not found in the email",
                value=item.value, evidence=item.evidence,
            ))
            continue
        result.spans[f"other_criteria[{len(kept)}]"] = span
        kept.append(item)
    cleaned.other_criteria = kept
    return result
