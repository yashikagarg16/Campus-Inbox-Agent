from datetime import date

from app.imap_sync import build_criteria, fetch_headers
from tools.collect_eval_emails import collect, list_senders


def test_gmail_keyword_search_uses_gmail_syntax():
    c = build_criteria("imap.gmail.com", date(2025, 7, 1), keywords=["placement", "CGPA"])
    assert c == ["X-GM-RAW", '"after:2025/07/01 (placement OR CGPA)"']
    c = build_criteria("imap.gmail.com", date(2025, 7, 1), sender="tpo@x.edu", keywords=["placement"])
    assert c[1].endswith('from:tpo@x.edu"')


def test_generic_imap_keyword_search_ors_terms():
    c = build_criteria("imap.example.com", date(2025, 7, 1), keywords=["a", "b", "c"])
    assert c == ["SINCE", "01-Jul-2025", "OR", "TEXT", '"a"', "OR", "TEXT", '"b"', "TEXT", '"c"']


def test_fetch_headers_reads_headers_only():
    fetched = []

    class FakeIMAP:
        def __init__(self, host): pass
        def login(self, u, p): pass
        def select(self, mailbox, readonly=False):
            assert readonly
            return "OK", [b"1"]
        def search(self, charset, *criteria): return "OK", [b"1"]
        def fetch(self, msg_id, parts):
            fetched.append(parts)
            return "OK", [(b"1", b"From: TPO <tpo@x.edu>\r\nSubject: Acme drive\r\nDate: Wed, 07 Oct 2026 04:30:00 +0000\r\n\r\n")]
        def logout(self): pass

    rows = list(fetch_headers("imap.gmail.com", "u", "p", date(2026, 1, 1), keywords=["drive"], connect=FakeIMAP))
    assert rows == [{"from": "TPO <tpo@x.edu>", "subject": "Acme drive", "date": "Wed, 07 Oct 2026 04:30:00 +0000"}]
    assert fetched == ["(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])"]


def test_list_senders_groups_by_address():
    rows = list_senders([{"from": "TPO <TPO@x.edu>", "subject": "a"}, {"from": "tpo@x.edu", "subject": "b"},
                         {"from": "news@y.com", "subject": "c"}])
    assert rows[0] == ("tpo@x.edu", 2, ["a", "b"])


def _eml(body: str) -> bytes:
    return ("Subject: Acme drive for s99xyzu0001\r\nDate: Wed, 07 Oct 2026 04:30:00 +0000\r\n"
            "Content-Type: text/plain; charset=utf-8\r\n\r\n" + body).encode()


def test_collect_redacts_and_dedupes():
    body = "Dear s99xyzu0001, Acme is hiring. Batch 2027. Contact tpo@college.edu or 9876543210 for details."
    recs = collect([_eml(body), _eml(body)], ["s99xyzu0001"], existing=[])
    assert len(recs) == 1
    text = recs[0]["text"]
    assert "s99xyzu0001" not in text and "9876543210" not in text and "tpo@college.edu" not in text
    assert "Batch 2027" in text
    assert recs[0]["subject"] == "Acme drive for [NAME]"
    assert recs[0]["id"] == "real-001" and recs[0]["received_at"] == "2026-10-07T10:00"
    assert collect([_eml(body)], ["s99xyzu0001"], existing=recs) == []
