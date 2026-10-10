"""Accounts and free-usage limits.

Roles:
- user:  signed up through the app
- owner: configured by ADMIN_EMAIL / ADMIN_PASSWORD_HASH; no usage limit; may sync the inbox
- demo:  owns the public sample data; nobody can sign in as it
- local: single-user mode when the server has no sign-in configured
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth import hash_password, verify_password
from .models import AuditEvent, EmailRow, ProfileRow, UsageRow, UserRow
from .schemas import local_now

DEMO_EMAIL = "demo@campus-inbox-agent.local"
LOCAL_EMAIL = "local@localhost"
UNLIMITED_ROLES = {"owner", "local"}
MIN_PASSWORD = 10
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class SignupError(ValueError):
    pass


class QuotaExceeded(Exception):
    pass


@dataclass
class Actor:
    """Who is making a request, and whether they may change anything."""

    user_id: int
    email: str
    role: str
    can_write: bool


def normalize_email(email: str) -> str:
    return email.strip().lower()


def ensure_user(session: Session, email: str, role: str, password_hash: str | None = None) -> UserRow:
    """Get or create a built-in account (owner, demo, local). Keeps the owner's hash in sync with env."""
    email = normalize_email(email)
    user = session.scalars(select(UserRow).where(UserRow.email == email)).first()
    if user is None:
        try:
            user = UserRow(email=email, role=role, password_hash=password_hash)
            session.add(user)
            session.commit()
            return user
        except IntegrityError:  # another server instance created it at the same moment
            session.rollback()
            user = session.scalars(select(UserRow).where(UserRow.email == email)).one()
    if user.role != role or (password_hash is not None and user.password_hash != password_hash):
        user.role = role
        if password_hash is not None:
            user.password_hash = password_hash
        session.commit()
    return user


def create_user(session: Session, email: str, password: str) -> UserRow:
    email = normalize_email(email)
    if not _EMAIL_RE.match(email) or len(email) > 320:
        raise SignupError("Enter a valid email address.")
    if email in (DEMO_EMAIL, LOCAL_EMAIL):
        raise SignupError("That email can't be used.")
    if len(password) < MIN_PASSWORD:
        raise SignupError(f"Use a password of at least {MIN_PASSWORD} characters.")
    if session.scalars(select(UserRow).where(UserRow.email == email)).first() is not None:
        raise SignupError("An account with this email already exists. Sign in instead.")
    user = UserRow(email=email, role="user", password_hash=hash_password(password))
    session.add(user)
    session.commit()
    return user


def authenticate(session: Session, email: str, password: str) -> UserRow | None:
    user = session.scalars(select(UserRow).where(UserRow.email == normalize_email(email))).first()
    if user is None or not user.password_hash:
        verify_password(password, hash_password("timing-equaliser"))  # same work whether or not the user exists
        return None
    return user if verify_password(password, user.password_hash) else None


def _today() -> str:
    return local_now().date().isoformat()


def usage_today(session: Session, user_id: int) -> int:
    row = session.scalars(select(UsageRow).where(UsageRow.user_id == user_id, UsageRow.day == _today())).first()
    return row.llm_calls if row else 0


def consume_llm_call(session: Session, actor: Actor, per_user_limit: int, global_limit: int) -> None:
    """Count one LLM-backed action, or raise QuotaExceeded if a limit is reached."""
    if actor.role not in UNLIMITED_ROLES:
        if usage_today(session, actor.user_id) >= per_user_limit:
            raise QuotaExceeded(f"You've used today's {per_user_limit} free email checks. They reset at midnight IST.")
        total = session.scalar(select(func.coalesce(func.sum(UsageRow.llm_calls), 0))
                               .join(UserRow, UserRow.id == UsageRow.user_id)
                               .where(UsageRow.day == _today(), UserRow.role.notin_(UNLIMITED_ROLES)))
        if total >= global_limit:
            raise QuotaExceeded("The app has reached today's free usage limit. Please try again tomorrow.")
    row = session.scalars(select(UsageRow).where(UsageRow.user_id == actor.user_id, UsageRow.day == _today())).first()
    if row is None:
        session.add(UsageRow(user_id=actor.user_id, day=_today(), llm_calls=1))
    else:
        row.llm_calls += 1
    session.commit()


def delete_account(session: Session, user: UserRow) -> None:
    """Remove the user and everything they stored."""
    email_ids = list(session.scalars(select(EmailRow.id).where(EmailRow.user_id == user.id)))
    # Audit rows first: they reference emails, and can contain email text.
    for row in session.scalars(select(AuditEvent).where(
            (AuditEvent.user_id == user.id) | AuditEvent.email_id.in_(email_ids))).all():
        session.delete(row)
    session.flush()
    for email in session.scalars(select(EmailRow).where(EmailRow.user_id == user.id)).all():
        session.delete(email)  # cascades to opportunities, rules, decisions, drafts
    for row in session.scalars(select(ProfileRow).where(ProfileRow.user_id == user.id)).all():
        session.delete(row)
    for row in session.scalars(select(UsageRow).where(UsageRow.user_id == user.id)).all():
        session.delete(row)
    session.flush()
    session.delete(user)
    session.commit()
