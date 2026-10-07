"""The pipeline: email -> clean -> extract -> guard -> rules -> decision, with an audit trail."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import rules
from .extractor import ExtractionFailed, LLMClient, OpportunityOutcome, draft_answers, draft_warnings, extract
from .imap_sync import fetch_raw_messages
from .models import AuditEvent, DecisionRow, DraftRow, EmailRow, OpportunityRow, ProfileRow, RuleRow
from .parsing import clean_text, parse_eml
from .schemas import EVIDENCED_FIELDS, ELIGIBILITY_FIELDS, Decision, DraftStatus, Extraction, FieldIssue, Profile


def audit(session: Session, event: str, email_id: int | None = None, opportunity_id: int | None = None,
          **detail) -> None:
    session.add(AuditEvent(event=event, email_id=email_id, opportunity_id=opportunity_id, detail=detail))


# --- profile -----------------------------------------------------------------------------------

def get_profile(session: Session) -> Profile:
    row = session.get(ProfileRow, 1)
    return Profile.model_validate(row.data) if row else Profile()


def save_profile(session: Session, profile: Profile) -> int:
    """Save the profile and re-run the rules on every opportunity. No LLM calls needed."""
    row = session.get(ProfileRow, 1)
    if row is None:
        session.add(ProfileRow(id=1, data=profile.model_dump(mode="json")))
    else:
        row.data = profile.model_dump(mode="json")
    audit(session, "profile_updated")
    opportunities = session.scalars(select(OpportunityRow)).all()
    for opp in opportunities:
        evaluate_opportunity(session, opp, profile)
    session.commit()
    return len(opportunities)


# --- decisions ---------------------------------------------------------------------------------

def evaluate_opportunity(session: Session, opp: OpportunityRow, profile: Profile,
                         now: datetime | None = None) -> DecisionRow:
    extraction = Extraction.model_validate(opp.extraction)
    issues = [FieldIssue.model_validate(i) for i in opp.issues]
    spans = {k: tuple(v) for k, v in opp.spans.items()}
    decision = rules.evaluate(extraction, profile, issues, spans, now=now)
    row = DecisionRow(opportunity=opp, verdict=decision.verdict.value,
                      result=decision.model_dump(mode="json"), profile_snapshot=profile.model_dump(mode="json"))
    session.add(row)
    session.flush()
    audit(session, "decision_made", email_id=opp.email_id, opportunity_id=opp.id,
          verdict=decision.verdict.value, decision_id=row.id)
    return row


def latest_decision(opp: OpportunityRow) -> Decision | None:
    return Decision.model_validate(opp.decisions[-1].result) if opp.decisions else None


# --- ingestion ---------------------------------------------------------------------------------

def content_hash(cleaned_text: str) -> str:
    return hashlib.sha256(" ".join(cleaned_text.split()).lower().encode()).hexdigest()


def find_duplicate(session: Session, cleaned: str, message_id: str | None) -> EmailRow | None:
    """An already-extracted email with the same Message-ID or the same text."""
    query = select(EmailRow).where(EmailRow.status == "extracted")
    if message_id:
        found = session.scalars(query.where(EmailRow.message_id == message_id)).first()
        if found:
            return found
    return session.scalars(query.where(EmailRow.content_hash == content_hash(cleaned))).first()


@dataclass
class IngestResult:
    email: EmailRow
    duplicate: bool = False


def ingest_email(session: Session, client: LLMClient, text: str, subject: str | None = None,
                 sender: str | None = None, received_at: datetime | None = None,
                 message_id: str | None = None, source: str = "paste") -> IngestResult:
    """Run the whole pipeline on one email. Raises ExtractionFailed after storing the failure."""
    cleaned = clean_text(text)
    existing = find_duplicate(session, cleaned, message_id)
    if existing is not None:
        return IngestResult(existing, duplicate=True)

    email = EmailRow(subject=subject, sender=sender, raw_text=text, cleaned_text=cleaned,
                     received_at=received_at, message_id=message_id, content_hash=content_hash(cleaned),
                     source=source)
    session.add(email)
    session.flush()
    audit(session, "email_received", email_id=email.id, chars=len(cleaned), source=source)

    try:
        outcome = extract(client, cleaned, received_at)
    except ExtractionFailed as e:
        email.status, email.error = "failed", str(e)
        audit(session, "extraction_failed", email_id=email.id, error=str(e), raw_responses=e.raw_responses)
        session.commit()
        raise

    email.status = "extracted"
    audit(session, "extraction_done", email_id=email.id, attempts=outcome.attempts,
          opportunities=len(outcome.opportunities), raw_responses=outcome.raw_responses)

    profile = get_profile(session)
    for position, item in enumerate(outcome.opportunities):
        opp = _store_opportunity(email, position, item)
        session.add(opp)
        session.flush()
        if item.issues:
            audit(session, "evidence_rejected", email_id=email.id, opportunity_id=opp.id,
                  issues=[i.model_dump(mode="json") for i in item.issues])
        evaluate_opportunity(session, opp, profile)
    session.commit()
    return IngestResult(email)


def _store_opportunity(email: EmailRow, position: int, item: OpportunityOutcome) -> OpportunityRow:
    ex = item.extraction
    opp = OpportunityRow(
        email=email, position=position, company=ex.company.value, role=ex.role.value,
        deadline=ex.deadline.value, form_link=ex.form_link.value, extraction=ex.model_dump(mode="json"),
        issues=[i.model_dump(mode="json") for i in item.issues],
        spans={k: list(v) for k, v in item.spans.items()},
    )
    for name in EVIDENCED_FIELDS:
        value = getattr(ex, name)
        if value.value is not None and name in ELIGIBILITY_FIELDS:
            _add_rule(opp, name, value.model_dump(mode="json")["value"], value.evidence, item.spans.get(name))
    for i, crit in enumerate(ex.other_criteria):
        _add_rule(opp, "other_criteria", crit.value, crit.evidence, item.spans.get(f"other_criteria[{i}]"))
    return opp


def _add_rule(opp: OpportunityRow, rule_type: str, value, evidence: str | None, span) -> None:
    opp.rules.append(RuleRow(rule_type=rule_type, value=value, evidence=evidence,
                             span_start=span[0] if span else None, span_end=span[1] if span else None))


# --- IMAP sync ---------------------------------------------------------------------------------

@dataclass
class SyncResult:
    fetched: int = 0
    new: int = 0
    duplicates: int = 0
    failed: int = 0
    email_ids: list[int] = field(default_factory=list)


def sync_imap(session: Session, client: LLMClient, settings, since: date, limit: int = 25,
              fetch=fetch_raw_messages) -> SyncResult:
    result = SyncResult()
    messages = fetch(settings.imap_host, settings.imap_user, settings.imap_password, since,
                     mailbox=settings.imap_mailbox, sender=settings.imap_sender_filter, limit=limit)
    for raw in messages:
        result.fetched += 1
        parsed = parse_eml(raw)
        if len(parsed.body) < 20:
            continue
        try:
            outcome = ingest_email(session, client, parsed.body, subject=parsed.subject, sender=parsed.sender,
                                   received_at=parsed.received_at, message_id=parsed.message_id, source="imap")
        except ExtractionFailed:
            result.failed += 1
            continue
        if outcome.duplicate:
            result.duplicates += 1
        else:
            result.new += 1
            result.email_ids.append(outcome.email.id)
    audit(session, "imap_sync", fetched=result.fetched, new=result.new, duplicates=result.duplicates,
          failed=result.failed, since=since.isoformat())
    session.commit()
    return result


# --- drafts ------------------------------------------------------------------------------------

def _opportunity_facts(opp: OpportunityRow) -> str:
    ex = opp.extraction
    facts = {k: ex[k]["value"] for k in EVIDENCED_FIELDS if ex.get(k, {}).get("value") is not None}
    facts["other_criteria"] = [c["value"] for c in ex.get("other_criteria", [])]
    return json.dumps(facts, ensure_ascii=False)


def create_drafts(session: Session, client: LLMClient, opp: OpportunityRow, questions: list[str]) -> list[DraftRow]:
    profile = get_profile(session)
    profile_json = profile.model_dump_json(exclude_none=True)
    facts = _opportunity_facts(opp)
    answers = draft_answers(client, profile_json, facts, questions)
    known = profile_json + facts + opp.email.cleaned_text
    rows = []
    for question, answer in zip(questions, answers):
        row = DraftRow(opportunity=opp, question=question, answer=answer,
                       warnings=draft_warnings(answer, known + question))
        session.add(row)
        rows.append(row)
    session.flush()
    audit(session, "drafts_created", email_id=opp.email_id, opportunity_id=opp.id, count=len(rows))
    session.commit()
    return rows


class DraftNotReady(ValueError):
    pass


def update_draft(session: Session, draft: DraftRow, answer: str | None, status: DraftStatus | None) -> DraftRow:
    if answer is not None:
        draft.answer = answer.strip()
        draft.warnings = draft_warnings(
            draft.answer,
            get_profile(session).model_dump_json(exclude_none=True) + _opportunity_facts(draft.opportunity)
            + draft.opportunity.email.cleaned_text + draft.question,
        )
        if status is None:
            draft.status = DraftStatus.DRAFT.value  # an edit needs re-approval
    if status is not None:
        if status is DraftStatus.APPROVED and any(w.startswith("Fill in:") for w in draft.warnings):
            raise DraftNotReady("Fill in every [NEEDS INPUT] placeholder before approving.")
        draft.status = status.value
    audit(session, "draft_updated", email_id=draft.opportunity.email_id, opportunity_id=draft.opportunity_id,
          draft_id=draft.id, status=draft.status)
    session.commit()
    return draft
