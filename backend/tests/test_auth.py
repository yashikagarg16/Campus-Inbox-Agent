import json

from fastapi.testclient import TestClient

from app.auth import LoginThrottle, hash_password, make_token, read_token, verify_password
from app.config import Settings
from app.main import create_app

from .helpers import SAMPLE_EMAIL, SAMPLE_RESPONSE, FakeLLM

SECRET = "test-secret"
OWNER = dict(admin_email="owner@example.com", admin_password_hash=hash_password("correct horse battery"),
             session_secret=SECRET)


def test_password_hash_roundtrip_and_salting():
    h = hash_password("hunter2hunter2")
    assert verify_password("hunter2hunter2", h)
    assert not verify_password("wrong", h)
    assert h != hash_password("hunter2hunter2")  # random salt
    assert not verify_password("x", "garbage")


def test_tokens_expire_and_reject_tampering():
    t = make_token("a@b.c", SECRET, ttl=60, now=1000)
    assert read_token(t, SECRET, now=1030) == "a@b.c"
    assert read_token(t, SECRET, now=1061) is None
    assert read_token(t, "other-secret", now=1030) is None
    body, sig = t.split(".")
    assert read_token(body + "x." + sig, SECRET, now=1030) is None
    assert read_token("not-a-token", SECRET) is None


def test_throttle_blocks_after_failures():
    th = LoginThrottle(limit=2, window=60)
    th.fail("1.2.3.4", now=0)
    th.fail("1.2.3.4", now=1)
    assert th.blocked("1.2.3.4", now=2)
    assert not th.blocked("1.2.3.4", now=100)
    assert not th.blocked("5.6.7.8", now=2)


def _login(c, password="correct horse battery", email="Owner@Example.com"):
    return c.post("/auth/login", json={"email": email, "password": password})


def test_private_server_requires_sign_in():
    llm = FakeLLM(json.dumps(SAMPLE_RESPONSE))
    c = TestClient(create_app(Settings(database_url="sqlite://", **OWNER), llm_factory=lambda: llm))
    cfg = c.get("/config").json()
    assert cfg["auth_required"] and cfg["owner_login"]
    assert c.get("/opportunities").status_code == 401
    assert _login(c, "wrong").status_code == 401
    r = _login(c)
    assert r.status_code == 200
    h = {"Authorization": f"Bearer {r.json()['token']}"}
    assert c.get("/auth/me", headers=h).json() == {"email": "owner@example.com", "role": "owner",
                                                   "usage_today": 0, "daily_limit": None}
    assert c.post("/emails", json={"text": SAMPLE_EMAIL}, headers=h).status_code == 201


def test_demo_visitors_read_owner_previews_nothing_stored():
    llm = FakeLLM(json.dumps(SAMPLE_RESPONSE))
    c = TestClient(create_app(Settings(database_url="sqlite://", demo_mode=True, **OWNER), llm_factory=lambda: llm))
    before = len(c.get("/opportunities").json())
    assert before == 38  # visitors can read without signing in
    assert c.post("/preview", json={"text": SAMPLE_EMAIL}).status_code == 401
    assert c.post("/emails", json={"text": SAMPLE_EMAIL}).status_code == 403
    assert c.get("/auth/me").status_code == 401

    h = {"Authorization": f"Bearer {_login(c).json()['token']}"}
    r = c.post("/preview", json={"text": SAMPLE_EMAIL, "received_at": "2026-10-07T09:00:00"}, headers=h)
    assert r.status_code == 200, r.text
    opp = r.json()["opportunities"][0]
    assert opp["company"] == "Acme Analytics" and opp["decision"]["rules"]
    assert len(c.get("/opportunities").json()) == before  # visitors' view unchanged
    assert c.get("/opportunities", headers=h).json() == []  # the owner has their own (empty) account


def test_login_disabled_without_owner_config():
    c = TestClient(create_app(Settings(database_url="sqlite://")))
    assert _login(c).status_code == 404
