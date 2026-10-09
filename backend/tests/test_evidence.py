from datetime import datetime

import pytest

from app.evidence import find_span, guard, years_in
from app.schemas import Extraction

from .helpers import SAMPLE_EMAIL, SAMPLE_RESPONSE, ev, make_extraction


def test_exact_quote_found_with_correct_span():
    text = "Hello.\nMinimum CGPA 8.0 required.\nBye"
    start, end = find_span(text, "Minimum CGPA 8.0 required.")
    assert text[start:end] == "Minimum CGPA 8.0 required"


def test_quote_survives_whitespace_case_and_smart_quotes():
    text = "Register  only if you’re\n8.5+ out of 10 – strictly."
    span = find_span(text, "register only if you're 8.5+ out of 10 - strictly")
    assert span is not None
    assert text[span[0]:span[1]].startswith("Register")


def test_quote_survives_dropped_markdown_bold():
    assert find_span("**Last date:** 20 Oct", "Last date: 20 Oct") is not None


def test_paraphrase_is_rejected():
    assert find_span(SAMPLE_EMAIL, "CGPA of at least 8.0 is needed") is None


def test_too_short_quote_is_rejected():
    assert find_span(SAMPLE_EMAIL, "8.0") is None


def test_years_in_ranges():
    assert years_in("Batch 2026-2028") == {2026, 2027, 2028}
    assert years_in("2027-28 batch") == {2027, 2028}
    assert years_in("2025 to 2026") == {2025, 2026}
    assert years_in("'27 grads") == {2027}


def test_guard_accepts_good_extraction():
    result = guard(Extraction.model_validate(SAMPLE_RESPONSE), SAMPLE_EMAIL, datetime(2026, 10, 7))
    assert result.issues == []
    assert result.extraction.min_cgpa.value == 8.0
    s, e = result.spans["min_cgpa"]
    assert SAMPLE_EMAIL[s:e] == "Minimum CGPA 8.0 required"


def test_guard_rejects_hallucinated_evidence():
    ex = make_extraction(min_cgpa=ev(9.0, "Minimum CGPA 9.0 required."))
    result = guard(ex, SAMPLE_EMAIL)
    assert result.extraction.min_cgpa.value is None
    assert result.issues[0].field == "min_cgpa"
    assert "not found" in result.issues[0].reason


def test_guard_rejects_value_not_in_its_quote():
    # Real quote, wrong number: the LLM read 8.5 from somewhere else (or nowhere).
    ex = make_extraction(min_cgpa=ev(8.5, "Minimum CGPA 8.0 required."))
    result = guard(ex, SAMPLE_EMAIL)
    assert result.extraction.min_cgpa.value is None
    assert "does not appear" in result.issues[0].reason


def test_guard_rejects_batch_year_not_in_quote():
    ex = make_extraction(batches=ev([2026, 2027, 2028], "Batch 2027 and 2028 only."))
    result = guard(ex, SAMPLE_EMAIL)
    assert result.issues[0].field == "batches"


def test_guard_accepts_expanded_batch_range():
    text = "Eligible: Batch 2026-2028 students."
    result = guard(make_extraction(batches=ev([2026, 2027, 2028], "Batch 2026-2028 students")), text)
    assert result.issues == []


def test_guard_rejects_link_not_in_email():
    ex = make_extraction(form_link=ev("https://forms.gle/evil", "Register here: https://forms.gle/abc123XYZ"))
    result = guard(ex, SAMPLE_EMAIL)
    assert result.issues[0].field == "form_link"


def test_guard_rejects_deadline_day_not_in_quote():
    ex = make_extraction(deadline=ev("2026-10-21T17:00", "Last date: 20 Oct, 5 PM."))
    assert guard(ex, SAMPLE_EMAIL).issues[0].field == "deadline"


def test_guard_rejects_deadline_before_received_date():
    ex = make_extraction(deadline=ev("2025-10-20T17:00", "Last date: 20 Oct, 5 PM."))
    issues = guard(ex, SAMPLE_EMAIL, received_at=datetime(2026, 10, 7)).issues
    assert "earlier than" in issues[0].reason


def test_guard_accepts_zero_backlogs_in_words():
    text = "Students should not have any active backlogs."
    ex = make_extraction(max_active_backlogs=ev(0, "should not have any active backlogs"))
    assert guard(ex, text).issues == []


def test_guard_drops_unverified_other_criteria_but_reports_it():
    ex = make_extraction(other_criteria=[ev("strong academics", "strong academics required")])
    result = guard(ex, SAMPLE_EMAIL)
    assert result.extraction.other_criteria == []
    assert result.issues[0].field == "other_criteria"


def test_relative_deadline_tomorrow_resolved_from_received_date():
    text = "Registration closes tomorrow at 10 AM."
    ex = make_extraction(deadline=ev("2026-10-08T10:00", "Registration closes tomorrow at 10 AM."))
    assert guard(ex, text, received_at=datetime(2026, 10, 7, 13, 0)).issues == []


def test_relative_deadline_wrong_day_rejected():
    text = "Registration closes tomorrow at 10 AM."
    ex = make_extraction(deadline=ev("2026-10-09T10:00", "Registration closes tomorrow at 10 AM."))
    assert "relative date" in guard(ex, text, received_at=datetime(2026, 10, 7)).issues[0].reason


def test_relative_deadline_without_received_date_rejected():
    text = "Submit by today EOD."
    ex = make_extraction(deadline=ev("2026-10-07T23:59", "Submit by today EOD."))
    assert guard(ex, text).issues[0].field == "deadline"


# 2026-10-07 is a Wednesday.
@pytest.mark.parametrize("quote, deadline, ok", [
    ("Register by Friday, 5 PM.", "2026-10-09T17:00", True),
    ("Register by Fri 5 PM.", "2026-10-09T17:00", True),
    ("Register by Friday, 5 PM.", "2026-10-16T17:00", False),   # a week off
    ("Last date: this Monday.", "2026-10-12T23:59", True),
    ("Register by next Friday.", "2026-10-09T23:59", False),    # ambiguous
    ("Register by Wednesday.", "2026-10-07T23:59", False),      # same weekday: today or next week?
])
def test_weekday_deadlines(quote, deadline, ok):
    ex = make_extraction(deadline=ev(deadline, quote))
    issues = guard(ex, quote, received_at=datetime(2026, 10, 7, 9, 0)).issues
    assert (issues == []) is ok, issues


def test_weekday_deadline_quote_with_link_digits():
    quote = "Register by this Friday, 5 PM: https://forms.gle/synthWren030"
    ex = make_extraction(deadline=ev("2026-10-09T17:00", quote))
    assert guard(ex, quote, received_at=datetime(2026, 10, 7, 8, 0)).issues == []
