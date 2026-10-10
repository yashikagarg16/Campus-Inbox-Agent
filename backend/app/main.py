"""HTTP API. Read-only toward the outside world: it never submits forms or sends email.

Run with:  uvicorn app.main:create_app --factory

Every stored email, opportunity, draft and profile belongs to one account, and every query is
scoped to the account making the request. Visitors to a demo deployment read the demo account.
"""

from __future__ import annotations

import imaplib
import json
from datetime import datetime, timedelta
from typing import Any, Callable, Iterator

from fastapi import APIRouter, Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import service, users
from .auth import TOKEN_TTL_SECONDS, LoginThrottle, make_token, read_token
from .config import Settings
from .extractor import ExtractionFailed, LLMClient
from .graph_mail import GraphAuthRequired, GraphMail, get_token
from .models import BACKEND_DIR, AuditEvent, DraftRow, EmailRow, OpportunityRow, UserRow, make_sessionmaker
from .parsing import clean_text, parse_eml
from .schemas import Decision, DraftStatus, FieldIssue, Profile, local_now, to_local_naive
from .users import DEMO_EMAIL, LOCAL_EMAIL, Actor

MAX_EML_BYTES = 2_000_000
DEMO_SEED = BACKEND_DIR / "demo_data" / "seed.json"
READ_ONLY_DEMO = ("This is the read-only demo with synthetic emails. Create a free account to check your own "
                  "emails.")


# --- request / response shapes ------------------------------------------------------------------

class EmailIn(BaseModel):
    text: str = Field(min_length=20, max_length=100_000)
    subject: str | None = Field(default=None, max_length=500)
    sender: str | None = Field(default=None, max_length=320)
    received_at: datetime | None = None


class OpportunitySummary(BaseModel):
    id: int
    email_id: int
    subject: str | None
    company: str | None
    role: str | None
    deadline: datetime | None
    deadline_passed: bool | None
    form_link: str | None
    verdict: str | None
    is_opportunity: bool
    created_at: datetime


class DraftOut(BaseModel):
    id: int
    opportunity_id: int
    question: str
    answer: str
    status: str
    warnings: list[str]
    updated_at: datetime


class OpportunityDetail(OpportunitySummary):
    email_text: str
    received_at: datetime | None
    sender: str | None
    siblings: list[int]  # other opportunities from the same (digest) email
    extraction: dict[str, Any]
    issues: list[FieldIssue]
    decision: Decision | None
    drafts: list[DraftOut]


class IngestOut(BaseModel):
    email_id: int
    duplicate: bool
    opportunities: list[OpportunityDetail]


class AuditOut(BaseModel):
    id: int
    event: str
    email_id: int | None
    opportunity_id: int | None
    detail: dict[str, Any]
    created_at: datetime


class ProfileSaved(BaseModel):
    profile: Profile
    reevaluated: int


class DraftRequest(BaseModel):
    questions: list[str] = Field(min_length=1, max_length=20)


class DraftUpdate(BaseModel):
    answer: str | None = Field(default=None, max_length=10_000)
    status: DraftStatus | None = None


class SyncRequest(BaseModel):
    since_days: int = Field(default=7, ge=1, le=60)
    limit: int = Field(default=25, ge=1, le=100)


class SyncOut(BaseModel):
    fetched: int
    new: int
    duplicates: int
    failed: int
    email_ids: list[int]


class CredentialsIn(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=200)


class LoginOut(BaseModel):
    token: str
    email: str
    role: str
    expires_in: int


class MeOut(BaseModel):
    email: str
    role: str
    usage_today: int
    daily_limit: int | None  # None = unlimited


class PreviewOpportunity(BaseModel):
    company: str | None
    role: str | None
    deadline: datetime | None
    form_link: str | None
    verdict: str
    is_opportunity: bool
    extraction: dict[str, Any]
    issues: list[FieldIssue]
    decision: Decision


class PreviewOut(BaseModel):
    email_text: str
    opportunities: list[PreviewOpportunity]


class ConfigOut(BaseModel):
    demo_mode: bool = False
    owner_login: bool = False
    signup_enabled: bool = False
    user_daily_limit: int | None = None
    llm_configured: bool
    imap_configured: bool  # any inbox sync (IMAP or Outlook) is set up
    mail_source: str | None = None  # "graph" | "imap" | None
    auth_required: bool


def _summary_fields(opp: OpportunityRow) -> dict[str, Any]:
    decision = service.latest_decision(opp)
    passed = opp.deadline < local_now() if opp.deadline else None
    return dict(
        id=opp.id, email_id=opp.email_id, subject=opp.email.subject, company=opp.company, role=opp.role,
        deadline=opp.deadline, deadline_passed=passed, form_link=opp.form_link,
        verdict=decision.verdict.value if decision else None,
        is_opportunity=opp.extraction.get("is_opportunity", True), created_at=opp.created_at,
    )


def _draft_out(d: DraftRow) -> DraftOut:
    return DraftOut(id=d.id, opportunity_id=d.opportunity_id, question=d.question, answer=d.answer,
                    status=d.status, warnings=d.warnings or [], updated_at=d.updated_at)


def _detail(opp: OpportunityRow) -> OpportunityDetail:
    return OpportunityDetail(
        **_summary_fields(opp), email_text=opp.email.cleaned_text, received_at=opp.email.received_at,
        sender=opp.email.sender, siblings=[o.id for o in opp.email.opportunities if o.id != opp.id],
        extraction=opp.extraction, issues=[FieldIssue.model_validate(i) for i in opp.issues],
        decision=service.latest_decision(opp), drafts=[_draft_out(d) for d in opp.drafts],
    )


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for") or (request.client.host if request.client else "")
    return forwarded.split(",")[0].strip()


# --- app ---------------------------------------------------------------------------------------

def create_app(settings: Settings | None = None, llm_factory: Callable[[], LLMClient] | None = None,
               imap_fetch: Callable | None = None, graph_fetch: Callable | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    if (settings.signup_enabled or (settings.admin_email and settings.admin_password_hash)) \
            and not settings.session_secret:
        raise RuntimeError("SESSION_SECRET must be set when sign-in or sign-up is enabled.")

    app = FastAPI(title="Campus Inbox Agent", version="0.3.0")
    app.state.sessionmaker = make_sessionmaker(settings.database_url, migrate=settings.migrate_on_startup)

    with app.state.sessionmaker() as session:
        if settings.owner_login:
            users.ensure_user(session, settings.admin_email, "owner", settings.admin_password_hash)
        if settings.demo_mode:
            demo = users.ensure_user(session, DEMO_EMAIL, "demo")
            service.seed_demo(session, json.loads(DEMO_SEED.read_text(encoding="utf-8")), demo.id)

    def default_llm() -> LLMClient:
        if not settings.gemini_api_key:
            raise HTTPException(503, "GEMINI_API_KEY is not set on the server.")
        return settings.gemini_client()

    app.state.llm_factory = llm_factory or default_llm
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"],
                       allow_headers=["*"])

    bearer = HTTPBearer(auto_error=False)
    login_throttle = LoginThrottle()
    signup_throttle = LoginThrottle(limit=5, window=3600)

    def get_session(request: Request) -> Iterator[Session]:
        with request.app.state.sessionmaker() as session:
            yield session

    def get_llm(request: Request) -> LLMClient:
        return request.app.state.llm_factory()

    def token_user(session: Session, token: str | None) -> UserRow | None:
        if not token:
            return None
        if settings.app_token and token == settings.app_token:
            return users.ensure_user(session, LOCAL_EMAIL, "local")  # scripts act as the local user
        if settings.session_secret:
            subject = read_token(token, settings.session_secret)
            if subject and subject.isdigit():
                return session.get(UserRow, int(subject))
        return None

    def get_actor(request: Request, creds: HTTPAuthorizationCredentials | None = Depends(bearer),
                  session: Session = Depends(get_session)) -> Actor:
        user = token_user(session, creds.credentials if creds else None)
        if user is not None and user.role != "demo":
            return Actor(user.id, user.email, user.role, can_write=True)
        if not settings.auth_required and not settings.demo_mode:
            local = users.ensure_user(session, LOCAL_EMAIL, "local")  # single-user mode
            return Actor(local.id, local.email, "local", can_write=True)
        if settings.demo_mode:
            demo = session.scalars(select(UserRow).where(UserRow.email == DEMO_EMAIL)).one()
            return Actor(demo.id, demo.email, "demo", can_write=False)
        raise HTTPException(401, "Please sign in.", headers={"WWW-Authenticate": "Bearer"})

    def writer(actor: Actor = Depends(get_actor)) -> Actor:
        if not actor.can_write:
            raise HTTPException(403, READ_ONLY_DEMO)
        return actor

    def signed_in(actor: Actor = Depends(get_actor)) -> Actor:
        if actor.role in ("demo", "local"):
            raise HTTPException(401, "Please sign in.", headers={"WWW-Authenticate": "Bearer"})
        return actor

    def consume(session: Session, actor: Actor) -> None:
        try:
            users.consume_llm_call(session, actor, settings.user_daily_limit, settings.global_daily_limit)
        except users.QuotaExceeded as e:
            raise HTTPException(429, str(e)) from e

    def get_opp(opp_id: int, session: Session, actor: Actor) -> OpportunityRow:
        opp = session.get(OpportunityRow, opp_id)
        if opp is None or opp.email.user_id != actor.user_id:
            raise HTTPException(404, "Opportunity not found.")
        return opp

    def get_draft(draft_id: int, session: Session, actor: Actor) -> DraftRow:
        draft = session.get(DraftRow, draft_id)
        if draft is None or draft.opportunity.email.user_id != actor.user_id:
            raise HTTPException(404, "Draft not found.")
        return draft

    def call_llm(session: Session, fn: Callable, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ExtractionFailed as e:
            raise HTTPException(422, f"The LLM output couldn't be used: {e}") from e
        except HTTPException:
            raise
        except Exception as e:  # network or quota errors from the LLM provider
            session.rollback()
            raise HTTPException(502, f"LLM call failed: {type(e).__name__}") from e

    def ingest(session: Session, llm: LLMClient, actor: Actor, response: Response, **kwargs) -> IngestOut:
        duplicate = service.find_duplicate(session, actor.user_id, clean_text(kwargs["text"]), kwargs.get("message_id"))
        if duplicate is not None:  # no LLM call needed, so it doesn't count against the limit
            response.status_code = 200
            return IngestOut(email_id=duplicate.id, duplicate=True,
                             opportunities=[_detail(o) for o in duplicate.opportunities])
        consume(session, actor)
        result: service.IngestResult = call_llm(session, service.ingest_email, session, llm,
                                                user_id=actor.user_id, **kwargs)
        return IngestOut(email_id=result.email.id, duplicate=result.duplicate,
                         opportunities=[_detail(o) for o in result.email.opportunities])

    def issue_token(user: UserRow) -> LoginOut:
        return LoginOut(token=make_token(str(user.id), settings.session_secret), email=user.email, role=user.role,
                        expires_in=TOKEN_TTL_SECONDS)

    # --- public ---------------------------------------------------------------------------------

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/config", response_model=ConfigOut)
    def read_config() -> ConfigOut:
        return ConfigOut(
            demo_mode=settings.demo_mode, owner_login=settings.owner_login or settings.signup_enabled,
            signup_enabled=settings.signup_enabled,
            user_daily_limit=settings.user_daily_limit if settings.signup_enabled else None,
            llm_configured=bool(settings.gemini_api_key) or llm_factory is not None,
            imap_configured=settings.mail_source is not None, mail_source=settings.mail_source,
            auth_required=settings.auth_required,
        )

    @app.post("/auth/signup", response_model=LoginOut, status_code=201)
    def signup(body: CredentialsIn, request: Request, session: Session = Depends(get_session)) -> LoginOut:
        if not settings.signup_enabled:
            raise HTTPException(404, "Sign-up isn't open on this server.")
        ip = _client_ip(request)
        if signup_throttle.blocked(ip):
            raise HTTPException(429, "Too many sign-ups from this network. Try again later.")
        signup_throttle.fail(ip)  # every attempt counts toward the hourly limit
        try:
            user = users.create_user(session, body.email, body.password)
        except users.SignupError as e:
            raise HTTPException(422, str(e)) from e
        service.audit(session, "account_created", user_id=user.id)
        session.commit()
        return issue_token(user)

    @app.post("/auth/login", response_model=LoginOut)
    def login(body: CredentialsIn, request: Request, session: Session = Depends(get_session)) -> LoginOut:
        if not (settings.owner_login or settings.signup_enabled):
            raise HTTPException(404, "Sign-in isn't set up on this server.")
        ip = _client_ip(request)
        if login_throttle.blocked(ip):
            raise HTTPException(429, "Too many attempts. Try again in a few minutes.")
        user = users.authenticate(session, body.email, body.password)
        if user is None or user.role == "demo":
            login_throttle.fail(ip)
            raise HTTPException(401, "Wrong email or password.")
        login_throttle.reset(ip)
        return issue_token(user)

    @app.get("/auth/me", response_model=MeOut)
    def me(actor: Actor = Depends(signed_in), session: Session = Depends(get_session)) -> MeOut:
        limit = None if actor.role in users.UNLIMITED_ROLES else settings.user_daily_limit
        return MeOut(email=actor.email, role=actor.role, usage_today=users.usage_today(session, actor.user_id),
                     daily_limit=limit)

    @app.delete("/auth/me", status_code=204)
    def delete_me(actor: Actor = Depends(signed_in), session: Session = Depends(get_session)) -> None:
        if actor.role != "user":
            raise HTTPException(403, "This built-in account can't be deleted from the app.")
        users.delete_account(session, session.get(UserRow, actor.user_id))

    @app.post("/preview", response_model=PreviewOut)
    def preview(body: EmailIn, actor: Actor = Depends(signed_in), session: Session = Depends(get_session),
                llm: LLMClient = Depends(get_llm)) -> PreviewOut:
        """Run the full pipeline on one email and return the result without storing anything."""
        consume(session, actor)
        received = to_local_naive(body.received_at) if body.received_at else local_now()
        cleaned, items = call_llm(session, service.preview_email, llm, body.text, received,
                                  service.get_profile(session, actor.user_id))
        return PreviewOut(email_text=cleaned, opportunities=[
            PreviewOpportunity(company=o.extraction.company.value, role=o.extraction.role.value,
                               deadline=o.extraction.deadline.value, form_link=o.extraction.form_link.value,
                               verdict=d.verdict.value, is_opportunity=o.extraction.is_opportunity,
                               extraction=o.extraction.model_dump(mode="json"), issues=o.issues, decision=d)
            for o, d in items
        ])

    # --- account data -----------------------------------------------------------------------------

    api = APIRouter()

    @api.get("/profile", response_model=Profile)
    def read_profile(actor: Actor = Depends(get_actor), session: Session = Depends(get_session)) -> Profile:
        return service.get_profile(session, actor.user_id)

    @api.put("/profile", response_model=ProfileSaved)
    def update_profile(profile: Profile, actor: Actor = Depends(writer),
                       session: Session = Depends(get_session)) -> ProfileSaved:
        count = service.save_profile(session, actor.user_id, profile)
        return ProfileSaved(profile=profile, reevaluated=count)

    @api.post("/emails", response_model=IngestOut, status_code=201)
    def submit_email(body: EmailIn, response: Response, actor: Actor = Depends(writer),
                     session: Session = Depends(get_session), llm: LLMClient = Depends(get_llm)) -> IngestOut:
        received = to_local_naive(body.received_at) if body.received_at else local_now()
        return ingest(session, llm, actor, response, text=body.text, subject=body.subject, sender=body.sender,
                      received_at=received)

    @api.post("/emails/eml", response_model=IngestOut, status_code=201)
    async def upload_eml(response: Response, file: UploadFile = File(...), actor: Actor = Depends(writer),
                         session: Session = Depends(get_session), llm: LLMClient = Depends(get_llm)) -> IngestOut:
        data = await file.read(MAX_EML_BYTES + 1)
        if len(data) > MAX_EML_BYTES:
            raise HTTPException(413, "File too large.")
        parsed = parse_eml(data)
        if len(parsed.body) < 20:
            raise HTTPException(422, "No readable text found in this email.")
        return ingest(session, llm, actor, response, text=parsed.body, subject=parsed.subject, sender=parsed.sender,
                      received_at=parsed.received_at or local_now(), message_id=parsed.message_id, source="eml")

    @api.delete("/emails/{email_id}", status_code=204)
    def delete_email(email_id: int, actor: Actor = Depends(writer), session: Session = Depends(get_session)) -> None:
        email = session.get(EmailRow, email_id)
        if email is None or email.user_id != actor.user_id:
            raise HTTPException(404, "Email not found.")
        opp_ids = [o.id for o in email.opportunities]
        for event in session.scalars(select(AuditEvent).where(
                (AuditEvent.email_id == email_id) | AuditEvent.opportunity_id.in_(opp_ids))):
            session.delete(event)  # audit details can contain email text
        session.flush()
        session.delete(email)
        service.audit(session, "email_deleted", user_id=actor.user_id, deleted_email_id=email_id)
        session.commit()

    @api.post("/sync/inbox", response_model=SyncOut)
    @api.post("/sync/imap", response_model=SyncOut, include_in_schema=False)  # older name
    def sync_inbox(body: SyncRequest, actor: Actor = Depends(writer), session: Session = Depends(get_session),
                   llm: LLMClient = Depends(get_llm)) -> SyncOut:
        if actor.role not in users.UNLIMITED_ROLES:
            raise HTTPException(403, "Inbox sync reads the server owner's mailbox, so only the owner can run it.")
        since = (local_now() - timedelta(days=body.since_days)).date()
        source = settings.mail_source
        if source is None:
            raise HTTPException(503, "No inbox sync is configured on the server (MS_CLIENT_ID for Outlook, "
                                     "or IMAP_HOST/IMAP_USER/IMAP_PASSWORD).")
        try:
            if source == "graph":
                fetch = graph_fetch or _graph_fetch
                messages = fetch(since, sender=settings.imap_sender_filter, limit=body.limit)
                result = service.sync_messages(session, llm, messages, since, "outlook", user_id=actor.user_id)
            else:
                kwargs = {"fetch": imap_fetch} if imap_fetch else {}
                result = service.sync_imap(session, llm, settings, since, limit=body.limit, user_id=actor.user_id,
                                           **kwargs)
        except GraphAuthRequired as e:
            raise HTTPException(503, str(e)) from e
        except imaplib.IMAP4.error as e:  # e.g. wrong app password
            raise HTTPException(502, f"Mail server refused the request: {e}") from e
        except OSError as e:  # includes requests' connection errors
            raise HTTPException(502, f"Couldn't reach the mail server: {type(e).__name__}") from e
        return SyncOut(**result.__dict__)

    def _graph_fetch(since, sender, limit):
        token = get_token(settings.ms_client_id, settings.ms_tenant, interactive=False)
        return GraphMail(token).raw_messages(since, sender=sender, limit=limit)

    @api.get("/opportunities", response_model=list[OpportunitySummary])
    def list_opportunities(actor: Actor = Depends(get_actor),
                           session: Session = Depends(get_session)) -> list[OpportunitySummary]:
        opps = service.user_opportunities(session, actor.user_id)
        opps = sorted(opps, key=lambda o: (o.deadline is None, o.deadline or datetime.max, -o.id))
        return [OpportunitySummary(**_summary_fields(o)) for o in opps]

    @api.get("/opportunities/{opp_id}", response_model=OpportunityDetail)
    def get_opportunity(opp_id: int, actor: Actor = Depends(get_actor),
                        session: Session = Depends(get_session)) -> OpportunityDetail:
        return _detail(get_opp(opp_id, session, actor))

    @api.get("/opportunities/{opp_id}/audit", response_model=list[AuditOut])
    def get_audit(opp_id: int, actor: Actor = Depends(get_actor),
                  session: Session = Depends(get_session)) -> list[AuditOut]:
        opp = get_opp(opp_id, session, actor)
        events = session.scalars(
            select(AuditEvent)
            .where((AuditEvent.opportunity_id == opp_id)
                   | ((AuditEvent.email_id == opp.email_id) & AuditEvent.opportunity_id.is_(None)))
            .order_by(AuditEvent.id)
        ).all()
        return [AuditOut.model_validate(e, from_attributes=True) for e in events]

    @api.post("/opportunities/{opp_id}/drafts", response_model=list[DraftOut], status_code=201)
    def create_drafts(opp_id: int, body: DraftRequest, actor: Actor = Depends(writer),
                      session: Session = Depends(get_session), llm: LLMClient = Depends(get_llm)) -> list[DraftOut]:
        questions = [q.strip() for q in body.questions if q.strip()]
        if not questions:
            raise HTTPException(422, "Add at least one question.")
        opp = get_opp(opp_id, session, actor)
        consume(session, actor)
        rows = call_llm(session, service.create_drafts, session, llm, opp, questions)
        return [_draft_out(d) for d in rows]

    @api.put("/drafts/{draft_id}", response_model=DraftOut)
    def update_draft(draft_id: int, body: DraftUpdate, actor: Actor = Depends(writer),
                     session: Session = Depends(get_session)) -> DraftOut:
        draft = get_draft(draft_id, session, actor)
        try:
            return _draft_out(service.update_draft(session, draft, body.answer, body.status))
        except service.DraftNotReady as e:
            raise HTTPException(422, str(e)) from e

    @api.delete("/drafts/{draft_id}", status_code=204)
    def delete_draft(draft_id: int, actor: Actor = Depends(writer), session: Session = Depends(get_session)) -> None:
        session.delete(get_draft(draft_id, session, actor))
        session.commit()

    app.include_router(api)
    return app
