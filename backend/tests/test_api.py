import copy
import os
import json

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, normalize_database_url
from app.main import create_app

from .helpers import SAMPLE_EMAIL, SAMPLE_RESPONSE, FakeLLM, ev

PROFILE = {"batch": 2027, "cgpa": 8.4, "branch": "CSE", "skills": ["Python"]}


@pytest.fixture
def llm():
    return FakeLLM()


def make_client(llm, **settings_kw):
    settings = Settings(database_url="sqlite://", gemini_api_key=None, **settings_kw)
    return TestClient(create_app(settings, llm_factory=lambda: llm))


@pytest.fixture
def client(llm):
    return make_client(llm)


def submit(client, llm, response=SAMPLE_RESPONSE, text=SAMPLE_EMAIL):
    llm.responses.append(json.dumps(response))
    return client.post("/emails", json={"text": text, "subject": "Acme", "received_at": "2026-10-07T09:00:00"})


def first(resp):
    return resp.json()["opportunities"][0]


def test_full_flow_eligible_with_evidence(client, llm):
    client.put("/profile", json=PROFILE)
    r = submit(client, llm)
    assert r.status_code == 201, r.text
    body = first(r)
    assert body["verdict"] == "eligible"
    assert body["company"] == "Acme Analytics"
    cgpa_rule = next(x for x in body["decision"]["rules"] if x["rule"] == "min_cgpa")
    start, end = cgpa_rule["span"]
    assert body["email_text"][start:end] == "Minimum CGPA 8.0 required"


def test_profile_change_reevaluates_without_llm(client, llm):
    client.put("/profile", json=PROFILE)
    opp_id = first(submit(client, llm))["id"]
    r = client.put("/profile", json={**PROFILE, "cgpa": 7.5})
    assert r.json()["reevaluated"] == 1
    assert client.get(f"/opportunities/{opp_id}").json()["verdict"] == "not_eligible"
    assert len(llm.prompts) == 1


def test_hallucinated_field_becomes_needs_review(client, llm):
    client.put("/profile", json=PROFILE)
    bad = copy.deepcopy(SAMPLE_RESPONSE)
    bad["min_cgpa"] = ev(7.0, "Minimum CGPA 7.0 required.")
    llm.responses += [json.dumps(bad)] * 2
    body = first(submit(client, llm, bad))
    assert body["verdict"] == "needs_review"
    assert body["issues"][0]["field"] == "min_cgpa"
    events = [e["event"] for e in client.get(f"/opportunities/{body['id']}/audit").json()]
    assert events[:2] == ["email_received", "extraction_done"]
    assert "evidence_rejected" in events and "decision_made" in events


def test_duplicate_email_is_not_reprocessed(client, llm):
    r1 = submit(client, llm)
    llm.responses.clear()
    r2 = client.post("/emails", json={"text": SAMPLE_EMAIL.replace("Dear", "dear  ")})
    assert r2.status_code == 200
    assert r2.json()["duplicate"] is True
    assert r2.json()["email_id"] == r1.json()["email_id"]
    assert len(llm.prompts) == 1


def test_digest_email_creates_one_opportunity_each(client, llm):
    client.put("/profile", json=PROFILE)
    other = copy.deepcopy(SAMPLE_RESPONSE)
    other["company"] = ev("Training & Placement Cell", "Training & Placement Cell")
    other["batches"] = ev([2028], "Batch 2027 and 2028 only.")
    r = submit(client, llm, {"opportunities": [SAMPLE_RESPONSE, other]})
    opps = r.json()["opportunities"]
    assert [o["verdict"] for o in opps] == ["eligible", "not_eligible"]
    assert opps[0]["siblings"] == [opps[1]["id"]]
    assert len(client.get("/opportunities").json()) == 2


def test_unparseable_output_returns_422_and_is_audited(client, llm):
    llm.responses += ["nope", "nope", "nope"]
    r = client.post("/emails", json={"text": SAMPLE_EMAIL})
    assert r.status_code == 422


def test_failed_email_can_be_retried(client, llm):
    llm.responses += ["nope", "nope", "nope"]
    client.post("/emails", json={"text": SAMPLE_EMAIL})
    assert submit(client, llm).status_code == 201  # not treated as a duplicate


def test_list_sorted_by_deadline(client, llm):
    later = copy.deepcopy(SAMPLE_RESPONSE)
    no_deadline = copy.deepcopy(SAMPLE_RESPONSE)
    no_deadline["deadline"] = ev(None)
    submit(client, llm, no_deadline)
    submit(client, llm, later, text=SAMPLE_EMAIL + "\nPS: reminder")
    deadlines = [o["deadline"] for o in client.get("/opportunities").json()]
    assert deadlines == ["2026-10-20T17:00:00", None]


def test_missing_api_key_gives_503():
    app = create_app(Settings(database_url="sqlite://", gemini_api_key=None))
    r = TestClient(app).post("/emails", json={"text": SAMPLE_EMAIL})
    assert r.status_code == 503


def test_eml_upload_uses_message_id_for_dedup(client, llm):
    llm.responses.append(json.dumps(SAMPLE_RESPONSE))
    eml = ("Subject: Acme\r\nMessage-ID: <abc@college.edu>\r\nDate: Wed, 07 Oct 2026 04:30:00 +0000\r\n"
           "Content-Type: text/plain; charset=utf-8\r\n\r\n" + SAMPLE_EMAIL.replace("\n", "\r\n")).encode()
    r = client.post("/emails/eml", files={"file": ("mail.eml", eml, "message/rfc822")})
    assert r.status_code == 201, r.text
    assert first(r)["subject"] == "Acme"
    again = client.post("/emails/eml", files={"file": ("mail.eml", eml + b"\r\nforwarded", "message/rfc822")})
    assert again.json()["duplicate"] is True


def test_delete_email_removes_everything(client, llm):
    r = submit(client, llm)
    email_id, opp_id = r.json()["email_id"], first(r)["id"]
    assert client.delete(f"/emails/{email_id}").status_code == 204
    assert client.get(f"/opportunities/{opp_id}").status_code == 404
    assert client.get("/opportunities").json() == []


def test_unknown_opportunity_404(client):
    assert client.get("/opportunities/999").status_code == 404


# --- auth --------------------------------------------------------------------------------------

def test_token_required_when_configured(llm):
    c = make_client(llm, app_token="s3cret")
    assert c.get("/health").status_code == 200
    assert c.get("/opportunities").status_code == 401
    assert c.get("/opportunities", headers={"Authorization": "Bearer wrong"}).status_code == 401
    ok = c.get("/opportunities", headers={"Authorization": "Bearer s3cret"})
    assert ok.status_code == 200
    assert c.get("/config", headers={"Authorization": "Bearer s3cret"}).json()["auth_required"] is True


# --- drafts ------------------------------------------------------------------------------------

def test_draft_edit_approve_flow(client, llm):
    client.put("/profile", json={**PROFILE, "name": "Test Student"})
    opp_id = first(submit(client, llm))["id"]
    llm.responses.append(json.dumps({"answers": [
        {"question": "Why Acme?", "answer": "I like analytics. [NEEDS INPUT: a project you did]"},
        {"question": "Your CGPA?", "answer": "8.4"},
    ]}))
    r = client.post(f"/opportunities/{opp_id}/drafts", json={"questions": ["Why Acme?", "Your CGPA?"]})
    assert r.status_code == 201, r.text
    d1, d2 = r.json()
    assert d1["warnings"] == ["Fill in: [NEEDS INPUT: a project you did]"]
    assert d2["warnings"] == []

    blocked = client.put(f"/drafts/{d1['id']}", json={"status": "approved"})
    assert blocked.status_code == 422

    fixed = client.put(f"/drafts/{d1['id']}", json={"answer": "I built a dashboard in Python.", "status": "approved"})
    assert fixed.json()["status"] == "approved"
    edited = client.put(f"/drafts/{d1['id']}", json={"answer": "Changed again"})
    assert edited.json()["status"] == "draft"  # edits need re-approval

    detail = client.get(f"/opportunities/{opp_id}").json()
    assert len(detail["drafts"]) == 2
    assert client.delete(f"/drafts/{d2['id']}").status_code == 204


def test_drafts_require_questions(client, llm):
    opp_id = first(submit(client, llm))["id"]
    assert client.post(f"/opportunities/{opp_id}/drafts", json={"questions": ["  "]}).status_code == 422


# --- IMAP --------------------------------------------------------------------------------------

def _eml(msg_id: str) -> bytes:
    return (f"Subject: Acme\r\nMessage-ID: <{msg_id}>\r\nDate: Wed, 07 Oct 2026 04:30:00 +0000\r\n"
            "Content-Type: text/plain; charset=utf-8\r\n\r\n" + SAMPLE_EMAIL).encode()


def test_imap_sync(llm):
    calls = {}

    def fake_fetch(host, user, password, since, mailbox, sender, limit):
        calls.update(host=host, since=since, limit=limit)
        return iter([_eml("one@x"), _eml("one@x"), b"Subject: empty\r\n\r\nhi"])

    settings = Settings(database_url="sqlite://", imap_host="imap.example.com", imap_user="u", imap_password="p")
    c = TestClient(create_app(settings, llm_factory=lambda: llm, imap_fetch=fake_fetch))
    llm.responses.append(json.dumps(SAMPLE_RESPONSE))
    r = c.post("/sync/imap", json={"since_days": 3, "limit": 10})
    assert r.status_code == 200, r.text
    assert r.json() | {"email_ids": None} == {"fetched": 3, "new": 1, "duplicates": 1, "failed": 0, "email_ids": None}
    assert calls["host"] == "imap.example.com" and calls["limit"] == 10


def test_imap_not_configured(client):
    assert client.post("/sync/imap", json={}).status_code == 503


def test_fetch_raw_messages_is_read_only():
    from app.imap_sync import fetch_raw_messages
    from datetime import date

    log = []

    class FakeIMAP:
        def __init__(self, host): log.append(("connect", host))
        def login(self, u, p): log.append(("login", u))
        def select(self, mailbox, readonly=False):
            log.append(("select", mailbox, readonly))
            return "OK", [b"2"]
        def search(self, charset, *criteria):
            log.append(("search", criteria))
            return "OK", [b"1 2"]
        def fetch(self, msg_id, parts):
            log.append(("fetch", parts))
            return "OK", [(b"1 (BODY[] {3}", b"raw"), b")"]
        def logout(self): log.append(("logout",))

    msgs = list(fetch_raw_messages("h", "u", "p", date(2026, 10, 1), sender="tpo@x.edu", connect=FakeIMAP))
    assert msgs == [b"raw", b"raw"]
    assert ("select", '"INBOX"', True) in log
    assert all(entry[1] == "(BODY.PEEK[])" for entry in log if entry[0] == "fetch")
    assert ("search", ("SINCE", "01-Oct-2026", "FROM", '"tpo@x.edu"')) in log
    assert log[-1] == ("logout",)


# --- config / migrations -----------------------------------------------------------------------

def test_postgres_url_normalized():
    assert normalize_database_url("postgres://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert normalize_database_url("sqlite:///x.db") == "sqlite:///x.db"


def test_migrations_build_a_working_database(tmp_path, llm):
    url = f"sqlite:///{(tmp_path / 'm.db').as_posix()}"
    c = TestClient(create_app(Settings(database_url=url), llm_factory=lambda: llm))
    assert submit(c, llm).status_code == 201
    # Restarting runs migrations again and must be a no-op.
    c2 = TestClient(create_app(Settings(database_url=url), llm_factory=lambda: llm))
    assert len(c2.get("/opportunities").json()) == 1


@pytest.mark.skipif(not os.getenv("TEST_POSTGRES_URL"), reason="set TEST_POSTGRES_URL to run against PostgreSQL")
def test_full_flow_on_postgres(llm):
    from sqlalchemy import create_engine, text

    url = normalize_database_url(os.environ["TEST_POSTGRES_URL"])
    with create_engine(url).begin() as conn:  # start from an empty schema
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    c = TestClient(create_app(Settings(database_url=url), llm_factory=lambda: llm))
    c.put("/profile", json=PROFILE)
    r = submit(c, llm)
    assert r.status_code == 201, r.text
    opp = first(r)
    assert opp["verdict"] == "eligible"
    llm.responses.append(json.dumps({"answers": [{"question": "q", "answer": "a"}]}))
    assert c.post(f"/opportunities/{opp['id']}/drafts", json={"questions": ["q"]}).status_code == 201
    assert c.delete(f"/emails/{opp['email_id']}").status_code == 204
    assert c.get("/opportunities").json() == []


def test_demo_mode_is_seeded_and_read_only():
    c = TestClient(create_app(Settings(database_url="sqlite://", demo_mode=True)))
    assert c.get("/config").json()["demo_mode"] is True
    opps = c.get("/opportunities").json()
    assert len(opps) == 38
    verdicts = {o["verdict"] for o in opps}
    assert {"eligible", "not_eligible", "needs_review"} <= verdicts
    detail = c.get(f"/opportunities/{opps[0]['id']}").json()
    assert any(r["span"] for r in detail["decision"]["rules"]) or not detail["decision"]["rules"]
    for method, path, body in [("post", "/emails", {"text": SAMPLE_EMAIL}), ("put", "/profile", PROFILE),
                               ("delete", f"/emails/{opps[0]['email_id']}", None), ("post", "/sync/inbox", {})]:
        r = getattr(c, method)(path, json=body) if body is not None else getattr(c, method)(path)
        assert r.status_code == 403, (method, path)
    assert c.get("/profile").json()["name"] == "Demo Student"
