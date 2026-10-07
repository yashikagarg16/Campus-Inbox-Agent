import json
from datetime import date

from fastapi.testclient import TestClient

from app.config import Settings
from app.graph_mail import GraphAuthRequired, GraphMail, build_query
from app.main import create_app

from .helpers import SAMPLE_EMAIL, SAMPLE_RESPONSE, FakeLLM


class FakeResponse:
    def __init__(self, payload=None, content=b""):
        self._payload, self.content = payload, content

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, routes):
        self.headers = {}
        self.routes = routes
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        return self.routes[url] if not callable(self.routes[url]) else self.routes[url](params)


def test_query_combines_date_keywords_and_sender():
    assert build_query(date(2025, 7, 1), "tpo@x.edu", ["placement", "CGPA"]) == \
        "received>=2025-07-01 AND (placement OR CGPA) AND from:tpo@x.edu"


def test_headers_follow_paging_and_respect_limit():
    page2 = "https://graph.microsoft.com/v1.0/me/messages?page=2"
    msg = lambda i: {"subject": f"s{i}", "receivedDateTime": "2026-10-01T10:00:00Z",
                     "from": {"emailAddress": {"name": "TPO", "address": "tpo@x.edu"}}}
    session = FakeSession({
        "https://graph.microsoft.com/v1.0/me/messages": FakeResponse({"value": [msg(1), msg(2)], "@odata.nextLink": page2}),
        page2: FakeResponse({"value": [msg(3), msg(4)]}),
    })
    rows = list(GraphMail("tok", session).headers(date(2025, 7, 1), ["placement"], limit=3))
    assert [r["subject"] for r in rows] == ["s1", "s2", "s3"]
    assert rows[0]["from"] == "TPO <tpo@x.edu>"
    assert session.headers["Authorization"] == "Bearer tok"
    first_params = session.calls[0][1]
    assert first_params["$search"] == '"received>=2025-07-01 AND (placement)"'
    assert session.calls[1][1] is None  # nextLink already has the query


def test_raw_messages_fetch_mime_and_quote_ids():
    session = FakeSession({
        "https://graph.microsoft.com/v1.0/me/messages": FakeResponse({"value": [{"id": "AA/B+C="}]}),
        "https://graph.microsoft.com/v1.0/me/messages/AA%2FB%2BC%3D/$value": FakeResponse(content=b"MIME"),
    })
    assert list(GraphMail("tok", session).raw_messages(date(2025, 7, 1))) == [b"MIME"]


def test_identity_lists_names_for_redaction():
    session = FakeSession({"https://graph.microsoft.com/v1.0/me": FakeResponse(
        {"displayName": "Test Student", "userPrincipalName": "s99xyzu0001@college.edu"})})
    assert GraphMail("tok", session).identity() == ["Test Student", "s99xyzu0001", "Student", "Test"]


def _eml(msg_id):
    return (f"Subject: Acme\r\nMessage-ID: <{msg_id}>\r\nDate: Wed, 07 Oct 2026 04:30:00 +0000\r\n"
            "Content-Type: text/plain; charset=utf-8\r\n\r\n" + SAMPLE_EMAIL).encode()


def test_inbox_sync_uses_outlook_when_configured():
    llm = FakeLLM(json.dumps(SAMPLE_RESPONSE))
    seen = {}

    def fake_graph(since, sender, limit):
        seen.update(limit=limit)
        return iter([_eml("a@x"), _eml("a@x")])

    app = create_app(Settings(database_url="sqlite://", ms_client_id="cid"), llm_factory=lambda: llm,
                     graph_fetch=fake_graph)
    c = TestClient(app)
    assert c.get("/config").json()["mail_source"] == "graph"
    r = c.post("/sync/inbox", json={"limit": 5})
    assert r.status_code == 200, r.text
    assert r.json()["new"] == 1 and r.json()["duplicates"] == 1
    assert seen["limit"] == 5


def test_inbox_sync_without_sign_in_explains_what_to_do():
    def not_signed_in(since, sender, limit):
        raise GraphAuthRequired("Not signed in to Outlook yet. Run: python -m tools.fetch_outlook --sign-in")

    app = create_app(Settings(database_url="sqlite://", ms_client_id="cid"), llm_factory=FakeLLM,
                     graph_fetch=not_signed_in)
    r = TestClient(app).post("/sync/inbox", json={})
    assert r.status_code == 503
    assert "fetch_outlook --sign-in" in r.json()["detail"]
