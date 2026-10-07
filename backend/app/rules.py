"""Rule engine: plain Python decides eligibility. No LLM here.

Each rule returns PASS, FAIL or UNKNOWN. The verdict is:
- NOT_ELIGIBLE if any rule FAILs (a verified requirement you don't meet),
- NEEDS_REVIEW if any rule is UNKNOWN, or no checkable rule was found,
- ELIGIBLE only if every rule PASSes.

The engine leans to UNKNOWN: a FAIL becomes UNKNOWN when the email hedges
("or equivalent", "may be relaxed"), and branch names it cannot map confidently
are never a FAIL.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

from .schemas import (
    ELIGIBILITY_FIELDS,
    Decision,
    Evidenced,
    Extraction,
    FieldIssue,
    Profile,
    RuleResult,
    RuleStatus,
    Verdict,
    local_now,
    to_local_naive,
)

EPS = 1e-9

HEDGE_RE = re.compile(
    r"\b(or equivalent|equivalent|preferred|preferably|desirable|relaxable|relaxed|relaxation|"
    r"may be considered|can be considered|flexible|negotiable|good to have|nice to have)\b",
    re.IGNORECASE,
)

RULE_LABELS = {
    "batches": "batch",
    "min_cgpa": "CGPA",
    "branches": "branch",
    "min_10th_percent": "10th percentage",
    "min_12th_percent": "12th percentage",
    "max_active_backlogs": "backlog",
    "required_skills": "skills",
    "other_criteria": "other",
}

_CIRCUIT = frozenset({"CSE", "IT", "ECE", "EEE", "EE"})
_BRANCH_ALIASES: dict[str, frozenset[str]] = {}
for canon, aliases in {
    "CSE": ["cse", "cs", "cs e", "computer science", "computer science and", "comp sci", "coe",
            "computer", "computer science and technology", "cst"],
    "IT": ["it", "information technology"],
    "ECE": ["ece", "ec", "electronics and communication", "electronics and communications",
            "electronics", "electronics and telecommunication", "entc", "e and tc", "etc"],
    "EEE": ["eee", "electrical and electronics", "electrical and electronic"],
    "EE": ["ee", "electrical"],
    "ME": ["me", "mech", "mechanical"],
    "CE": ["ce", "civil"],
    "CHE": ["che", "chemical"],
    "AIML": ["aiml", "ai ml", "ai and ml", "artificial intelligence and machine learning",
             "cse ai and ml", "cse aiml", "cse ai ml"],
    "DS": ["ds", "data science", "cse data science", "cse ds"],
    "MNC": ["mnc", "mathematics and computing", "maths and computing", "math and computing"],
    "EIE": ["eie", "ei", "electronics and instrumentation", "instrumentation", "ice",
            "instrumentation and control"],
    "BT": ["bt", "biotech", "biotechnology"],
    "AE": ["ae", "aero", "aerospace", "aeronautical"],
    "MME": ["mme", "metallurgy", "metallurgical and materials", "metallurgical"],
    "PIE": ["pie", "production", "production and industrial", "industrial and production", "ipe"],
}.items():
    for alias in aliases:
        _BRANCH_ALIASES[alias] = frozenset({canon})
for alias in ["circuit", "circuit branches", "circuital"]:
    _BRANCH_ALIASES[alias] = _CIRCUIT
for alias in ["all", "all branches", "any", "any branch", "all streams", "open to all",
              "all disciplines", "all departments"]:
    _BRANCH_ALIASES[alias] = frozenset({"ALL"})

# Specialisations colleges sometimes count under the parent branch and sometimes don't.
_RELATED_BRANCHES: dict[str, set[str]] = {
    "CSE": {"AIML", "DS"}, "AIML": {"CSE"}, "DS": {"CSE"},
    "EE": {"EEE"}, "EEE": {"EE"}, "ECE": {"EIE"}, "EIE": {"ECE"},
}

_BRANCH_NOISE = re.compile(r"\b(b ?tech|b ?e|m ?tech|engineering|engg|branch(es)?|dept|department|stream)\b")


def _branch_key(name: str) -> str:
    s = name.lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = _BRANCH_NOISE.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def canonicalize_branch(name: str) -> frozenset[str] | None:
    """Map a branch name to canonical codes, or None if it isn't recognised."""
    return _BRANCH_ALIASES.get(_branch_key(name))


def _hedged(evidence: str | None) -> str | None:
    if not evidence:
        return None
    m = HEDGE_RE.search(evidence)
    return m.group(0) if m else None


def _result(rule: str, field: Evidenced, status: RuleStatus, reason: str, required=None, actual=None,
            spans: dict | None = None, span_key: str | None = None) -> RuleResult:
    span = (spans or {}).get(span_key or rule)
    if status is RuleStatus.FAIL and (word := _hedged(field.evidence)):
        status = RuleStatus.UNKNOWN
        reason += f' But the email says "{word}", so the requirement may be flexible. Please check.'
    return RuleResult(rule=rule, status=status, required=required, actual=actual,
                      evidence=field.evidence, span=span, reason=reason)


def _missing_profile(rule: str, field: Evidenced, what: str, spans) -> RuleResult:
    return _result(rule, field, RuleStatus.UNKNOWN, f"Add your {what} to your profile to check this rule.",
                   required=field.value, spans=spans)


def _check_minimum(rule: str, field: Evidenced, actual: float | None, what: str, spans) -> RuleResult | None:
    if field.value is None:
        return None
    if actual is None:
        return _missing_profile(rule, field, what, spans)
    ok = actual + EPS >= field.value
    reason = (f"Your {what} {actual:g} meets the minimum {field.value:g}." if ok
              else f"Your {what} {actual:g} is below the minimum {field.value:g}.")
    return _result(rule, field, RuleStatus.PASS if ok else RuleStatus.FAIL, reason,
                   required=field.value, actual=actual, spans=spans)


def check_batch(ex: Extraction, p: Profile, spans=None) -> RuleResult | None:
    f = ex.batches
    if f.value is None:
        return None
    if p.batch is None:
        return _missing_profile("batches", f, "batch (graduation year)", spans)
    ok = p.batch in f.value
    allowed = ", ".join(str(y) for y in sorted(f.value))
    reason = f"Your batch {p.batch} is {'in' if ok else 'not in'} the allowed batches ({allowed})."
    return _result("batches", f, RuleStatus.PASS if ok else RuleStatus.FAIL, reason,
                   required=sorted(f.value), actual=p.batch, spans=spans)


def check_cgpa(ex: Extraction, p: Profile, spans=None) -> RuleResult | None:
    f = ex.min_cgpa
    if f.value is None:
        return None
    if p.cgpa is None:
        return _missing_profile("min_cgpa", f, "CGPA", spans)
    if abs(p.cgpa_scale - ex.cgpa_scale) > EPS:
        return _result("min_cgpa", f, RuleStatus.UNKNOWN,
                       f"The email uses a {ex.cgpa_scale:g}-point scale but your profile uses "
                       f"{p.cgpa_scale:g}. Scales can't be converted reliably, so please check.",
                       required=f.value, actual=p.cgpa, spans=spans)
    return _check_minimum("min_cgpa", f, p.cgpa, "CGPA", spans)


def check_branch(ex: Extraction, p: Profile, spans=None) -> RuleResult | None:
    f = ex.branches
    if f.value is None:
        return None
    if not p.branch:
        return _missing_profile("branches", f, "branch", spans)
    required = [canonicalize_branch(b) for b in f.value]
    known = set().union(*(r for r in required if r))
    my_names = [p.branch, *p.branch_aliases]
    mine = set().union(*(c for n in my_names if (c := canonicalize_branch(n))))
    if "ALL" in known:
        return _result("branches", f, RuleStatus.PASS, "The email says all branches are eligible.",
                       required=f.value, actual=p.branch, spans=spans)
    if mine & known or {_branch_key(n) for n in my_names} & {_branch_key(b) for b in f.value}:
        return _result("branches", f, RuleStatus.PASS, f"Your branch {p.branch} is in the eligible list.",
                       required=f.value, actual=p.branch, spans=spans)
    # A FAIL needs every name on both sides recognised; aliases you added count as recognised.
    if mine and set().union(*(_RELATED_BRANCHES.get(c, set()) for c in mine)) & known:
        return _result("branches", f, RuleStatus.UNKNOWN,
                       f"Your branch {p.branch} is closely related to one listed. Check whether "
                       f"specialisations count, and add the listed name to your branch aliases if so.",
                       required=f.value, actual=p.branch, spans=spans)
    if canonicalize_branch(p.branch) and all(required):
        return _result("branches", f, RuleStatus.FAIL, f"Your branch {p.branch} is not in the eligible list.",
                       required=f.value, actual=p.branch, spans=spans)
    return _result("branches", f, RuleStatus.UNKNOWN,
                   "Couldn't confidently match branch names between the email and your profile.",
                   required=f.value, actual=p.branch, spans=spans)


def check_tenth(ex: Extraction, p: Profile, spans=None) -> RuleResult | None:
    return _check_minimum("min_10th_percent", ex.min_10th_percent, p.tenth_percent, "10th percentage", spans)


def check_twelfth(ex: Extraction, p: Profile, spans=None) -> RuleResult | None:
    return _check_minimum("min_12th_percent", ex.min_12th_percent, p.twelfth_percent, "12th percentage", spans)


def check_backlogs(ex: Extraction, p: Profile, spans=None) -> RuleResult | None:
    f = ex.max_active_backlogs
    if f.value is None:
        return None
    if p.active_backlogs is None:
        return _missing_profile("max_active_backlogs", f, "number of active backlogs", spans)
    ok = p.active_backlogs <= f.value
    reason = f"You have {p.active_backlogs} active backlog(s); the maximum allowed is {f.value}."
    return _result("max_active_backlogs", f, RuleStatus.PASS if ok else RuleStatus.FAIL, reason,
                   required=f.value, actual=p.active_backlogs, spans=spans)


def check_skills(ex: Extraction, p: Profile, spans=None) -> RuleResult | None:
    f = ex.required_skills
    if f.value is None:
        return None
    mine = {s.strip().lower() for s in p.skills}
    missing = [s for s in f.value if s.strip().lower() not in mine]
    if not missing:
        return _result("required_skills", f, RuleStatus.PASS, "Your profile lists every skill mentioned.",
                       required=f.value, actual=p.skills, spans=spans)
    # Skill lists are often "preferred" and wording varies, so never a hard FAIL.
    return _result("required_skills", f, RuleStatus.UNKNOWN,
                   f"Your profile doesn't list: {', '.join(missing)}. Check whether these are mandatory.",
                   required=f.value, actual=p.skills, spans=spans)


CHECKS = (check_batch, check_cgpa, check_branch, check_tenth, check_twelfth, check_backlogs, check_skills)


def evaluate(
    extraction: Extraction,
    profile: Profile,
    issues: Iterable[FieldIssue] = (),
    spans: dict[str, tuple[int, int]] | None = None,
    now: datetime | None = None,
) -> Decision:
    spans = spans or {}
    issues = list(issues)
    results = [r for check in CHECKS if (r := check(extraction, profile, spans))]

    for issue in issues:
        if issue.field in ELIGIBILITY_FIELDS:
            label = RULE_LABELS[issue.field]
            results.append(RuleResult(
                rule=issue.field, status=RuleStatus.UNKNOWN, required=issue.value, evidence=issue.evidence,
                reason=f"The email seems to have a {label} requirement, but it couldn't be verified "
                       f"({issue.reason}). Please check the email.",
            ))

    for i, item in enumerate(extraction.other_criteria):
        results.append(RuleResult(
            rule="other_criteria", status=RuleStatus.UNKNOWN, required=item.value, evidence=item.evidence,
            span=spans.get(f"other_criteria[{i}]"),
            reason="This condition can't be checked automatically. Please check it yourself.",
        ))

    statuses = [r.status for r in results]
    if RuleStatus.FAIL in statuses:
        verdict = Verdict.NOT_ELIGIBLE
        reasons = [r.reason for r in results if r.status is RuleStatus.FAIL]
    elif RuleStatus.UNKNOWN in statuses:
        verdict = Verdict.NEEDS_REVIEW
        reasons = [r.reason for r in results if r.status is RuleStatus.UNKNOWN]
    elif not results:
        verdict = Verdict.NEEDS_REVIEW
        reasons = ["No eligibility criteria were found in this email. Check the full email before applying."]
    else:
        verdict = Verdict.ELIGIBLE
        reasons = [r.reason for r in results]

    notes = []
    if not extraction.is_opportunity:
        notes.append("This email doesn't look like an application or opportunity.")
        if verdict is Verdict.ELIGIBLE:
            verdict = Verdict.NEEDS_REVIEW
            reasons = ["This email doesn't look like an opportunity, so it needs a manual look."]

    issue_fields = {i.field for i in issues}
    deadline = extraction.deadline.value
    deadline_passed = None
    if deadline is None:
        notes.append("Deadline unclear, please check the email." if "deadline" in issue_fields
                     else "No deadline found in the email.")
    else:
        deadline_passed = deadline < (to_local_naive(now) if now else local_now())
        if deadline_passed:
            notes.append("The deadline has passed.")
    if "form_link" in issue_fields:
        notes.append("A form link was mentioned but couldn't be verified; copy it from the email directly.")

    return Decision(verdict=verdict, rules=results, reasons=reasons, notes=notes,
                    deadline=deadline, deadline_passed=deadline_passed)
