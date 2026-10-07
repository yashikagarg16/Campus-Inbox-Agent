"""Data shapes shared by the extractor, evidence guard, rule engine and API.

The extraction schema is the contract with the LLM: every value it extracts must
come with an `evidence` quote copied from the email. Code then verifies the quote.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Deadlines in campus emails are written in local time. All datetimes are stored
# naive, in this zone.
LOCAL_TZ = timezone(timedelta(hours=5, minutes=30), "IST")


def to_local_naive(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(LOCAL_TZ).replace(tzinfo=None)


def local_now() -> datetime:
    return datetime.now(LOCAL_TZ).replace(tzinfo=None)


T = TypeVar("T")


class Evidenced(BaseModel, Generic[T]):
    """A value plus the exact sentence from the email that states it."""

    value: T | None = None
    evidence: str | None = None

    @model_validator(mode="after")
    def _evidence_required(self) -> "Evidenced[T]":
        if isinstance(self.value, list) and not self.value:
            self.value = None
        if self.evidence is not None and not self.evidence.strip():
            self.evidence = None
        if self.value is not None and self.evidence is None:
            raise ValueError("a value was given without an evidence quote")
        return self


EVIDENCED_FIELDS = (
    "company",
    "role",
    "deadline",
    "form_link",
    "batches",
    "min_cgpa",
    "branches",
    "min_10th_percent",
    "min_12th_percent",
    "max_active_backlogs",
    "required_skills",
)

# Fields that decide eligibility. A rejected one makes the decision "needs review".
ELIGIBILITY_FIELDS = (
    "batches",
    "min_cgpa",
    "branches",
    "min_10th_percent",
    "min_12th_percent",
    "max_active_backlogs",
    "required_skills",
    "other_criteria",
)


def _empty(t: Any) -> Any:
    return Field(default_factory=lambda: Evidenced[t]())


class Extraction(BaseModel):
    """What the LLM must return for one email."""

    model_config = ConfigDict(extra="ignore")

    is_opportunity: bool = True
    company: Evidenced[str] = _empty(str)
    role: Evidenced[str] = _empty(str)
    deadline: Evidenced[datetime] = _empty(datetime)
    form_link: Evidenced[str] = _empty(str)
    batches: Evidenced[list[int]] = _empty(list[int])
    min_cgpa: Evidenced[float] = _empty(float)
    cgpa_scale: float = 10.0
    branches: Evidenced[list[str]] = _empty(list[str])
    min_10th_percent: Evidenced[float] = _empty(float)
    min_12th_percent: Evidenced[float] = _empty(float)
    max_active_backlogs: Evidenced[int] = _empty(int)
    required_skills: Evidenced[list[str]] = _empty(list[str])
    # Eligibility conditions code cannot check, e.g. "strong academics required".
    other_criteria: list[Evidenced[str]] = Field(default_factory=list)

    @field_validator(*EVIDENCED_FIELDS, mode="before")
    @classmethod
    def _null_is_empty(cls, v: Any) -> Any:
        return {} if v is None else v

    @field_validator("other_criteria", mode="before")
    @classmethod
    def _null_is_empty_list(cls, v: Any) -> Any:
        return [] if v is None else v

    @field_validator("cgpa_scale", mode="before")
    @classmethod
    def _default_scale(cls, v: Any) -> Any:
        return 10.0 if v is None else v

    @model_validator(mode="after")
    def _check_ranges(self) -> "Extraction":
        if self.deadline.value is not None:
            self.deadline.value = to_local_naive(self.deadline.value)
        self.other_criteria = [c for c in self.other_criteria if c.value is not None]

        if not 0 < self.cgpa_scale <= 100:
            raise ValueError(f"cgpa_scale must be between 0 and 100, got {self.cgpa_scale}")
        cgpa = self.min_cgpa.value
        if cgpa is not None and not 0 < cgpa <= self.cgpa_scale:
            raise ValueError(f"min_cgpa {cgpa} is outside 0..cgpa_scale ({self.cgpa_scale})")
        for name in ("min_10th_percent", "min_12th_percent"):
            pct = getattr(self, name).value
            if pct is not None and not 0 < pct <= 100:
                raise ValueError(f"{name} {pct} must be a percentage between 0 and 100")
        for year in self.batches.value or []:
            if not 2000 <= year <= 2100:
                raise ValueError(f"batch year {year} is not a 4-digit graduation year")
        backlogs = self.max_active_backlogs.value
        if backlogs is not None and backlogs < 0:
            raise ValueError("max_active_backlogs cannot be negative")
        return self


MAX_OPPORTUNITIES_PER_EMAIL = 20


class EmailExtraction(BaseModel):
    """One email can announce several openings (digest mails). Each gets its own Extraction."""

    opportunities: list[Extraction]

    @model_validator(mode="before")
    @classmethod
    def _accept_single(cls, data: Any) -> Any:
        # Tolerate an LLM that returns one opportunity object instead of the wrapper.
        if isinstance(data, dict) and "opportunities" not in data:
            return {"opportunities": [data]}
        return data

    @model_validator(mode="after")
    def _at_least_one(self) -> "EmailExtraction":
        if not self.opportunities:
            self.opportunities = [Extraction(is_opportunity=False)]
        if len(self.opportunities) > MAX_OPPORTUNITIES_PER_EMAIL:
            raise ValueError(f"at most {MAX_OPPORTUNITIES_PER_EMAIL} opportunities per email")
        return self


class Profile(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    batch: int | None = None
    cgpa: float | None = None
    cgpa_scale: float = 10.0
    branch: str | None = None
    tenth_percent: float | None = None
    twelfth_percent: float | None = None
    active_backlogs: int | None = None
    skills: list[str] = Field(default_factory=list)
    # Other names your branch goes by in emails, e.g. "CSE (AI&ML)" or "Mathematics and Computing".
    branch_aliases: list[str] = Field(default_factory=list)
    # Used only for drafting answers to form questions. Never sent anywhere else.
    resume_summary: str | None = Field(default=None, max_length=5000)

    @model_validator(mode="after")
    def _check_ranges(self) -> "Profile":
        if self.cgpa is not None and not 0 <= self.cgpa <= self.cgpa_scale:
            raise ValueError("cgpa must be between 0 and cgpa_scale")
        for name in ("tenth_percent", "twelfth_percent"):
            pct = getattr(self, name)
            if pct is not None and not 0 <= pct <= 100:
                raise ValueError(f"{name} must be between 0 and 100")
        if self.active_backlogs is not None and self.active_backlogs < 0:
            raise ValueError("active_backlogs cannot be negative")
        return self


class FieldIssue(BaseModel):
    """An extracted field the evidence guard refused to trust."""

    field: str
    reason: str
    value: Any = None
    evidence: str | None = None


class RuleStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    UNKNOWN = "unknown"


class Verdict(StrEnum):
    ELIGIBLE = "eligible"
    NOT_ELIGIBLE = "not_eligible"
    NEEDS_REVIEW = "needs_review"


class RuleResult(BaseModel):
    rule: str
    status: RuleStatus
    required: Any = None
    actual: Any = None
    evidence: str | None = None
    span: tuple[int, int] | None = None
    reason: str


class DraftStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"


class Decision(BaseModel):
    verdict: Verdict
    rules: list[RuleResult]
    reasons: list[str]
    notes: list[str]
    deadline: datetime | None = None
    deadline_passed: bool | None = None
