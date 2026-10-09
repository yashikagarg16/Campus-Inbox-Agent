"""Owner sign-in: a salted PBKDF2 password hash and HMAC-signed, expiring session tokens.

Only one account (the owner) exists; its email and password hash come from environment
variables. Generate a hash with:  python -m tools.hash_password
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time

ITERATIONS = 310_000
TOKEN_TTL_SECONDS = 7 * 24 * 3600


def hash_password(password: str, salt: str | None = None, iterations: int = ITERATIONS) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), iterations)
    return f"pbkdf2_sha256:{iterations}:{salt}:{digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, iterations, salt, expected = stored.split(":")
        if algorithm != "pbkdf2_sha256":
            return False
        candidate = hash_password(password, salt, int(iterations)).split(":")[3]
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(candidate, expected)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def make_token(subject: str, secret: str, ttl: int = TOKEN_TTL_SECONDS, now: float | None = None) -> str:
    payload = {"sub": subject, "exp": int((now or time.time()) + ttl)}
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    signature = _b64(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{signature}"


def read_token(token: str, secret: str, now: float | None = None) -> str | None:
    """The token's subject if its signature is valid and it hasn't expired, else None."""
    try:
        body, signature = token.split(".")
        expected = _b64(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            return None
        payload = json.loads(_unb64(body))
    except (ValueError, json.JSONDecodeError):
        return None
    if payload.get("exp", 0) < (now or time.time()):
        return None
    return payload.get("sub")


class LoginThrottle:
    """Slows down password guessing: after `limit` failures from one IP, refuse for `window` seconds."""

    def __init__(self, limit: int = 5, window: int = 300):
        self.limit, self.window = limit, window
        self._failures: dict[str, list[float]] = {}

    def blocked(self, ip: str, now: float | None = None) -> bool:
        now = now or time.time()
        recent = [t for t in self._failures.get(ip, []) if now - t < self.window]
        self._failures[ip] = recent
        return len(recent) >= self.limit

    def fail(self, ip: str, now: float | None = None) -> None:
        self._failures.setdefault(ip, []).append(now or time.time())

    def reset(self, ip: str) -> None:
        self._failures.pop(ip, None)
