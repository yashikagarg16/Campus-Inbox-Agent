"""The pipeline: email -> clean -> extract -> guard -> rules -> decision, with an audit trail."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import rules
from .extractor import ExtractionFailed, LLMClient, OpportunityOutcome, draft_answers, draft_warnings, extract
from .evidence import guard
from .imap_sync import fetch_raw_messages
from .models import AuditEvent, DecisionRow, DraftRow, EmailRow, OpportunityRow, ProfileRow, RuleRow
from .parsing import clean_text, parse_eml
from .schemas import EVIDENCED_FIELDS, ELIGIBILITY_FIELDS, Decision, DraftStatus, Extraction, FieldIssue, Profile


def audit(session: Session, event: str, email_id: int | None = None, opportunity_id: int | None = None,
          user_id: int | None = None, **detail) -> None:
    session.add(AuditEvent(event=event, email_id=email_id, opportunity_id=opportunity_id, user_id=user_id,
                           detail=detail))


# --- profile -----------------------------------------------------------------------------------

def get_profile(session: Session, user_id: int) -> Profile:
    row = session.scalars(select(ProfileRow).where(ProfileRow.user_id == user_id)).first()
    return Profile.model_validate(row.data) if row else Profile()


def user_opportunities(session: Session, user_id: int) -> list[OpportunityRow]:
    return list(session.scalars(
        select(OpportunityRow).join(EmailRow, EmailRow.id == OpportunityRow.email_id).where(EmailRow.user_id == user_id)
    ))


def save_profile(session: Session, user_id: int, profile: Profile) -> int:
    """Save the profile and re-run the rules on this user's opportunities. No LLM calls needed."""
    row = session.scalars(select(ProfileRow).where(ProfileRow.user_id == user_id)).first()
    if row is None:
        session.add(ProfileRow(user_id=user_id, data=profile.model_dump(mode="json")))
    else:
        row.data = profile.model_dump(mode="json")
    audit(session, "profile_updated", user_id=user_id)
    opportunities = user_opportunities(session, user_id)
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
    audit(session, "decision_made", email_id=opp.email_id, opportunity_id=opp.id, user_id=opp.email.user_id,
          verdict=decision.verdict.value, decision_id=row.id)
    return row


def latest_decision(opp: OpportunityRow) -> Decision | None:
    return Decision.model_validate(opp.decisions[-1].result) if opp.decisions else None


# --- ingestion ---------------------------------------------------------------------------------

def content_hash(cleaned_text: str) -> str:
    return hashlib.sha256(" ".join(cleaned_text.split()).lower().encode()).hexdigest()


def find_duplicate(session: Session, user_id: int, cleaned: str, message_id: str | None) -> EmailRow | None:
    """This user's already-extracted email with the same Message-ID or the same text."""
    query = select(EmailRow).where(EmailRow.status == "extracted", EmailRow.user_id == user_id)
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
                 message_id: str | None = None, source: str = "paste", *, user_id: int) -> IngestResult:
    """Run the whole pipeline on one email for one user. Raises ExtractionFailed after storing the failure."""
    cleaned = clean_text(text)
    existing = find_duplicate(session, user_id, cleaned, message_id)
    if existing is not None:
        return IngestResult(existing, duplicate=True)

    email = EmailRow(subject=subject, sender=sender, raw_text=text, cleaned_text=cleaned,
                     received_at=received_at, message_id=message_id, content_hash=content_hash(cleaned),
                     source=source, user_id=user_id)
    session.add(email)
    session.flush()
    audit(session, "email_received", email_id=email.id, user_id=user_id, chars=len(cleaned), source=source)

    try:
        outcome = extract(client, cleaned, received_at)
    except ExtractionFailed as e:
        email.status, email.error = "failed", str(e)
        audit(session, "extraction_failed", email_id=email.id, user_id=user_id, error=str(e),
              raw_responses=e.raw_responses)
        session.commit()
        raise

    email.status = "extracted"
    audit(session, "extraction_done", email_id=email.id, user_id=user_id, attempts=outcome.attempts,
          opportunities=len(outcome.opportunities), raw_responses=outcome.raw_responses)

    profile = get_profile(session, user_id)
    for position, item in enumerate(outcome.opportunities):
        opp = _store_opportunity(email, position, item)
        session.add(opp)
        session.flush()
        if item.issues:
            audit(session, "evidence_rejected", email_id=email.id, opportunity_id=opp.id, user_id=user_id,
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


def sync_messages(session: Session, client: LLMClient, messages: Iterable[bytes], since: date,
                  source: str, *, user_id: int) -> SyncResult:
    """Run raw RFC 822 messages (from IMAP or Outlook) through the pipeline, skipping duplicates."""
    result = SyncResult()
    for raw in messages:
        result.fetched += 1
        parsed = parse_eml(raw)
        if len(parsed.body) < 20:
            continue
        try:
            outcome = ingest_email(session, client, parsed.body, subject=parsed.subject, sender=parsed.sender,
                                   received_at=parsed.received_at, message_id=parsed.message_id, source=source,
                                   user_id=user_id)
        except ExtractionFailed:
            result.failed += 1
            continue
        if outcome.duplicate:
            result.duplicates += 1
        else:
            result.new += 1
            result.email_ids.append(outcome.email.id)
    audit(session, "inbox_sync", user_id=user_id, source=source, fetched=result.fetched, new=result.new,
          duplicates=result.duplicates, failed=result.failed, since=since.isoformat())
    session.commit()
    return result


def sync_imap(session: Session, client: LLMClient, settings, since: date, limit: int = 25,
              fetch=fetch_raw_messages, *, user_id: int) -> SyncResult:
    messages = fetch(settings.imap_host, settings.imap_user, settings.imap_password, since,
                     mailbox=settings.imap_mailbox, sender=settings.imap_sender_filter, limit=limit)
    return sync_messages(session, client, messages, since, "imap", user_id=user_id)


# --- live preview (nothing stored) -----------------------------------------------------------

def preview_email(client: LLMClient, text: str, received_at: datetime | None,
                  profile: Profile) -> tuple[str, list[tuple[OpportunityOutcome, Decision]]]:
    cleaned = clean_text(text)
    outcome = extract(client, cleaned, received_at)
    return cleaned, [(o, rules.evaluate(o.extraction, profile, o.issues, o.spans)) for o in outcome.opportunities]


# --- demo seed --------------------------------------------------------------------------------

def seed_demo(session: Session, seed: dict, user_id: int) -> int:
    """Load synthetic emails with stored (real) extractions into the demo account. No LLM calls."""
    if session.scalars(select(EmailRow).where(EmailRow.user_id == user_id).limit(1)).first() is not None:
        return 0
    profile = Profile.model_validate(seed["profile"])
    session.add(ProfileRow(user_id=user_id, data=profile.model_dump(mode="json")))
    for item in seed["emails"]:
        cleaned = clean_text(item["text"])
        received = datetime.fromisoformat(item["received_at"]) if item.get("received_at") else None
        email = EmailRow(subject=item.get("subject"), raw_text=item["text"], cleaned_text=cleaned, received_at=received,
                         content_hash=content_hash(cleaned), source="demo", status="extracted", user_id=user_id)
        session.add(email)
        for position, opp in enumerate(item["opportunities"]):
            checked = guard(Extraction.model_validate(opp["extraction"]), cleaned, received)  # recompute spans
            issues = [FieldIssue.model_validate(i) for i in opp["issues"]] + checked.issues
            row = _store_opportunity(email, position, OpportunityOutcome(checked.extraction, issues, checked.spans))
            session.add(row)
            session.flush()
            evaluate_opportunity(session, row, profile)
    session.commit()
    return len(seed["emails"])


# --- drafts ------------------------------------------------------------------------------------

def _opportunity_facts(opp: OpportunityRow) -> str:
    ex = opp.extraction
    facts = {k: ex[k]["value"] for k in EVIDENCED_FIELDS if ex.get(k, {}).get("value") is not None}
    facts["other_criteria"] = [c["value"] for c in ex.get("other_criteria", [])]
    return json.dumps(facts, ensure_ascii=False)


def create_drafts(session: Session, client: LLMClient, opp: OpportunityRow, questions: list[str]) -> list[DraftRow]:
    profile = get_profile(session, opp.email.user_id)
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
    audit(session, "drafts_created", email_id=opp.email_id, opportunity_id=opp.id, user_id=opp.email.user_id,
          count=len(rows))
    session.commit()
    return rows


class DraftNotReady(ValueError):
    pass


def update_draft(session: Session, draft: DraftRow, answer: str | None, status: DraftStatus | None) -> DraftRow:
    if answer is not None:
        draft.answer = answer.strip()
        draft.warnings = draft_warnings(
            draft.answer,
            get_profile(session, draft.opportunity.email.user_id).model_dump_json(exclude_none=True)
            + _opportunity_facts(draft.opportunity)
            + draft.opportunity.email.cleaned_text + draft.question,
        )
        if status is None:
            draft.status = DraftStatus.DRAFT.value  # an edit needs re-approval
    if status is not None:
        if status is DraftStatus.APPROVED and any(w.startswith("Fill in:") for w in draft.warnings):
            raise DraftNotReady("Fill in every [NEEDS INPUT] placeholder before approving.")
        draft.status = status.value
    audit(session, "draft_updated", email_id=draft.opportunity.email_id, opportunity_id=draft.opportunity_id,
          user_id=draft.opportunity.email.user_id, draft_id=draft.id, status=draft.status)
    session.commit()
    return draft
