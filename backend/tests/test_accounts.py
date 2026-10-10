import json

import pytest
from fastapi.testclient import TestClient

from app.auth import hash_password
from app.config import Settings
from app.main import create_app

from .helpers import SAMPLE_EMAIL, SAMPLE_RESPONSE

PROFILE = {"batch": 2027, "cgpa": 8.4, "branch": "CSE"}


class EndlessLLM:
    """Always returns the sample extraction, however many times it's called."""

    def generate(self, prompt):
        return json.dumps(SAMPLE_RESPONSE)


def app_client(**kw):
    settings = Settings(database_url="sqlite://", session_secret="s", signup_enabled=True, **kw)
    return TestClient(create_app(settings, llm_factory=lambda: EndlessLLM()))


def signup(c, email="a@example.com", password="long-password-1"):
    return c.post("/auth/signup", json={"email": email, "password": password})


def auth(r):
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_signup_then_full_private_flow():
    c = app_client()
    assert c.get("/config").json()["signup_enabled"] is True
    assert c.get("/opportunities").status_code == 401  # private server: sign in first
    r = signup(c)
    assert r.status_code == 201, r.text
    h = auth(r)
    me = c.get("/auth/me", headers=h).json()
    assert me == {"email": "a@example.com", "role": "user", "usage_today": 0, "daily_limit": 10}
    assert c.put("/profile", json=PROFILE, headers=h).status_code == 200
    assert c.post("/emails", json={"text": SAMPLE_EMAIL}, headers=h).status_code == 201
    opps = c.get("/opportunities", headers=h).json()
    assert len(opps) == 1 and opps[0]["verdict"] == "eligible"
    assert c.get("/auth/me", headers=h).json()["usage_today"] == 1


@pytest.mark.parametrize("email, password, message", [
    ("not-an-email", "long-password-1", "valid email"),
    ("b@example.com", "short", "at least 10"),
])
def test_signup_validation(email, password, message):
    r = signup(app_client(), email, password)
    assert r.status_code == 422 and message in r.json()["detail"]


def test_duplicate_signup_rejected_and_login_works_case_insensitively():
    c = app_client()
    signup(c, "Mixed@Example.com")
    assert signup(c, "mixed@example.com").status_code == 422
    assert c.post("/auth/login", json={"email": "MIXED@example.com", "password": "long-password-1"}).status_code == 200
    assert c.post("/auth/login", json={"email": "mixed@example.com", "password": "wrong-password"}).status_code == 401
    assert c.post("/auth/login", json={"email": "nobody@example.com", "password": "long-password-1"}).status_code == 401


def test_accounts_cannot_see_or_touch_each_other():
    c = app_client()
    a, b = auth(signup(c, "a@example.com")), auth(signup(c, "b@example.com"))
    c.put("/profile", json=PROFILE, headers=a)
    opp = c.post("/emails", json={"text": SAMPLE_EMAIL}, headers=a).json()["opportunities"][0]
    assert c.get("/opportunities", headers=b).json() == []
    assert c.get(f"/opportunities/{opp['id']}", headers=b).status_code == 404
    assert c.get(f"/opportunities/{opp['id']}/audit", headers=b).status_code == 404
    assert c.delete(f"/emails/{opp['email_id']}", headers=b).status_code == 404
    assert c.get("/profile", headers=b).json()["cgpa"] is None
    # The same email for B is not a "duplicate" of A's.
    assert c.post("/emails", json={"text": SAMPLE_EMAIL}, headers=b).json()["duplicate"] is False
    assert c.get(f"/opportunities/{opp['id']}", headers=a).status_code == 200


def test_daily_limit_per_account_and_duplicates_are_free():
    c = app_client(user_daily_limit=2)
    h = auth(signup(c))
    assert c.post("/emails", json={"text": SAMPLE_EMAIL}, headers=h).status_code == 201
    assert c.post("/emails", json={"text": SAMPLE_EMAIL}, headers=h).status_code == 200  # duplicate, not counted
    assert c.post("/emails", json={"text": SAMPLE_EMAIL + "\nPS 1"}, headers=h).status_code == 201
    r = c.post("/emails", json={"text": SAMPLE_EMAIL + "\nPS 2"}, headers=h)
    assert r.status_code == 429 and "free email checks" in r.json()["detail"]


def test_global_limit_across_accounts_owner_exempt():
    owner = dict(admin_email="owner@example.com", admin_password_hash=hash_password("owner-password-1"))
    c = app_client(global_daily_limit=1, **owner)
    a, b = auth(signup(c, "a@example.com")), auth(signup(c, "b@example.com"))
    assert c.post("/emails", json={"text": SAMPLE_EMAIL}, headers=a).status_code == 201
    assert c.post("/emails", json={"text": SAMPLE_EMAIL}, headers=b).status_code == 429
    o = auth(c.post("/auth/login", json={"email": "owner@example.com", "password": "owner-password-1"}))
    assert c.post("/emails", json={"text": SAMPLE_EMAIL}, headers=o).status_code == 201


def test_regular_users_cannot_sync_the_owners_inbox():
    c = app_client(imap_host="h", imap_user="u", imap_password="p")
    h = auth(signup(c))
    assert c.post("/sync/inbox", json={}, headers=h).status_code == 403


def test_delete_account_removes_everything():
    c = app_client()
    h = auth(signup(c))
    c.post("/emails", json={"text": SAMPLE_EMAIL}, headers=h)
    assert c.delete("/auth/me", headers=h).status_code == 204
    assert c.get("/auth/me", headers=h).status_code == 401  # token no longer maps to a user
    assert c.post("/auth/login", json={"email": "a@example.com", "password": "long-password-1"}).status_code == 401
    assert signup(c).status_code == 201  # the address is free again


def test_signup_closed_by_default():
    c = TestClient(create_app(Settings(database_url="sqlite://")))
    assert signup(c).status_code == 404


def test_sign_in_requires_session_secret():
    with pytest.raises(RuntimeError):
        create_app(Settings(database_url="sqlite://", signup_enabled=True))


def test_demo_plus_signup_users_get_their_own_space():
    c = TestClient(create_app(Settings(database_url="sqlite://", demo_mode=True, signup_enabled=True,
                                       session_secret="s"), llm_factory=lambda: EndlessLLM()))
    assert len(c.get("/opportunities").json()) == 38  # visitors see the demo
    h = auth(signup(c))
    assert c.get("/opportunities", headers=h).json() == []  # new users start empty
    assert c.post("/emails", json={"text": SAMPLE_EMAIL}, headers=h).status_code == 201
    assert len(c.get("/opportunities", headers=h).json()) == 1
    assert len(c.get("/opportunities").json()) == 38  # the demo is untouched
