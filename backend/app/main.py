"""HTTP API. Read-only toward the outside world: it never submits forms or sends email.

Run with:  uvicorn app.main:create_app --factory
"""

from __future__ import annotations

import imaplib
import secrets
from datetime import datetime, timedelta
from typing import Any, Callable, Iterator

from fastapi import APIRouter, Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import service
from .config import Settings
from .extractor import ExtractionFailed, GeminiClient, LLMClient
from .models import AuditEvent, DraftRow, EmailRow, OpportunityRow, make_sessionmaker
from .parsing import parse_eml
from .schemas import Decision, DraftStatus, FieldIssue, Profile, local_now, to_local_naive

MAX_EML_BYTES = 2_000_000


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


class ConfigOut(BaseModel):
    llm_configured: bool
    imap_configured: bool
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


# --- app ---------------------------------------------------------------------------------------

def create_app(settings: Settings | None = None, llm_factory: Callable[[], LLMClient] | None = None,
               imap_fetch: Callable | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    app = FastAPI(title="Campus Inbox Agent", version="0.2.0")
    app.state.sessionmaker = make_sessionmaker(settings.database_url, migrate=settings.migrate_on_startup)

    def default_llm() -> LLMClient:
        if not settings.gemini_api_key:
            raise HTTPException(503, "GEMINI_API_KEY is not set on the server.")
        return GeminiClient(settings.gemini_api_key, settings.gemini_model)

    app.state.llm_factory = llm_factory or default_llm
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"],
                       allow_headers=["*"])

    bearer = HTTPBearer(auto_error=False)

    def require_token(creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> None:
        if settings.app_token is None:
            return
        if creds is None or not secrets.compare_digest(creds.credentials.encode(), settings.app_token.encode()):
            raise HTTPException(401, "Missing or wrong access token.", headers={"WWW-Authenticate": "Bearer"})

    def get_session(request: Request) -> Iterator[Session]:
        with request.app.state.sessionmaker() as session:
            yield session

    def get_llm(request: Request) -> LLMClient:
        return request.app.state.llm_factory()

    def get_opp(opp_id: int, session: Session) -> OpportunityRow:
        opp = session.get(OpportunityRow, opp_id)
        if opp is None:
            raise HTTPException(404, "Opportunity not found.")
        return opp

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

    def ingest(session: Session, llm: LLMClient, response: Response, **kwargs) -> IngestOut:
        result: service.IngestResult = call_llm(session, service.ingest_email, session, llm, **kwargs)
        if result.duplicate:
            response.status_code = 200
        return IngestOut(email_id=result.email.id, duplicate=result.duplicate,
                         opportunities=[_detail(o) for o in result.email.opportunities])

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    api = APIRouter(dependencies=[Depends(require_token)])

    @api.get("/config", response_model=ConfigOut)
    def read_config() -> ConfigOut:
        return ConfigOut(llm_configured=bool(settings.gemini_api_key) or llm_factory is not None,
                         imap_configured=settings.imap_configured, auth_required=settings.app_token is not None)

    @api.get("/profile", response_model=Profile)
    def read_profile(session: Session = Depends(get_session)) -> Profile:
        return service.get_profile(session)

    @api.put("/profile", response_model=ProfileSaved)
    def update_profile(profile: Profile, session: Session = Depends(get_session)) -> ProfileSaved:
        count = service.save_profile(session, profile)
        return ProfileSaved(profile=profile, reevaluated=count)

    @api.post("/emails", response_model=IngestOut, status_code=201)
    def submit_email(body: EmailIn, response: Response, session: Session = Depends(get_session),
                     llm: LLMClient = Depends(get_llm)) -> IngestOut:
        received = to_local_naive(body.received_at) if body.received_at else local_now()
        return ingest(session, llm, response, text=body.text, subject=body.subject, sender=body.sender,
                      received_at=received)

    @api.post("/emails/eml", response_model=IngestOut, status_code=201)
    async def upload_eml(response: Response, file: UploadFile = File(...),
                         session: Session = Depends(get_session), llm: LLMClient = Depends(get_llm)) -> IngestOut:
        data = await file.read(MAX_EML_BYTES + 1)
        if len(data) > MAX_EML_BYTES:
            raise HTTPException(413, "File too large.")
        parsed = parse_eml(data)
        if len(parsed.body) < 20:
            raise HTTPException(422, "No readable text found in this email.")
        return ingest(session, llm, response, text=parsed.body, subject=parsed.subject, sender=parsed.sender,
                      received_at=parsed.received_at or local_now(), message_id=parsed.message_id, source="eml")

    @api.delete("/emails/{email_id}", status_code=204)
    def delete_email(email_id: int, session: Session = Depends(get_session)) -> None:
        email = session.get(EmailRow, email_id)
        if email is None:
            raise HTTPException(404, "Email not found.")
        opp_ids = [o.id for o in email.opportunities]
        for event in session.scalars(select(AuditEvent).where(
                (AuditEvent.email_id == email_id) | AuditEvent.opportunity_id.in_(opp_ids))):
            session.delete(event)  # audit details can contain email text
        session.flush()
        session.delete(email)
        service.audit(session, "email_deleted", deleted_email_id=email_id)
        session.commit()

    @api.post("/sync/imap", response_model=SyncOut)
    def sync_imap(body: SyncRequest, session: Session = Depends(get_session),
                  llm: LLMClient = Depends(get_llm)) -> SyncOut:
        if not settings.imap_configured:
            raise HTTPException(503, "IMAP is not configured on the server (IMAP_HOST, IMAP_USER, IMAP_PASSWORD).")
        since = (local_now() - timedelta(days=body.since_days)).date()
        kwargs = {"fetch": imap_fetch} if imap_fetch else {}
        try:
            result = service.sync_imap(session, llm, settings, since, limit=body.limit, **kwargs)
        except imaplib.IMAP4.error as e:  # e.g. wrong app password
            raise HTTPException(502, f"Mail server refused the request: {e}") from e
        except OSError as e:
            raise HTTPException(502, f"Couldn't reach the mail server: {type(e).__name__}") from e
        return SyncOut(**result.__dict__)

    @api.get("/opportunities", response_model=list[OpportunitySummary])
    def list_opportunities(session: Session = Depends(get_session)) -> list[OpportunitySummary]:
        opps = session.scalars(select(OpportunityRow)).all()
        opps = sorted(opps, key=lambda o: (o.deadline is None, o.deadline or datetime.max, -o.id))
        return [OpportunitySummary(**_summary_fields(o)) for o in opps]

    @api.get("/opportunities/{opp_id}", response_model=OpportunityDetail)
    def get_opportunity(opp_id: int, session: Session = Depends(get_session)) -> OpportunityDetail:
        return _detail(get_opp(opp_id, session))

    @api.get("/opportunities/{opp_id}/audit", response_model=list[AuditOut])
    def get_audit(opp_id: int, session: Session = Depends(get_session)) -> list[AuditOut]:
        opp = get_opp(opp_id, session)
        events = session.scalars(
            select(AuditEvent)
            .where((AuditEvent.opportunity_id == opp_id)
                   | ((AuditEvent.email_id == opp.email_id) & AuditEvent.opportunity_id.is_(None)))
            .order_by(AuditEvent.id)
        ).all()
        return [AuditOut.model_validate(e, from_attributes=True) for e in events]

    @api.post("/opportunities/{opp_id}/drafts", response_model=list[DraftOut], status_code=201)
    def create_drafts(opp_id: int, body: DraftRequest, session: Session = Depends(get_session),
                      llm: LLMClient = Depends(get_llm)) -> list[DraftOut]:
        questions = [q.strip() for q in body.questions if q.strip()]
        if not questions:
            raise HTTPException(422, "Add at least one question.")
        opp = get_opp(opp_id, session)
        rows = call_llm(session, service.create_drafts, session, llm, opp, questions)
        return [_draft_out(d) for d in rows]

    @api.put("/drafts/{draft_id}", response_model=DraftOut)
    def update_draft(draft_id: int, body: DraftUpdate, session: Session = Depends(get_session)) -> DraftOut:
        draft = session.get(DraftRow, draft_id)
        if draft is None:
            raise HTTPException(404, "Draft not found.")
        try:
            return _draft_out(service.update_draft(session, draft, body.answer, body.status))
        except service.DraftNotReady as e:
            raise HTTPException(422, str(e)) from e

    @api.delete("/drafts/{draft_id}", status_code=204)
    def delete_draft(draft_id: int, session: Session = Depends(get_session)) -> None:
        draft = session.get(DraftRow, draft_id)
        if draft is None:
            raise HTTPException(404, "Draft not found.")
        session.delete(draft)
        session.commit()

    app.include_router(api)
    return app
