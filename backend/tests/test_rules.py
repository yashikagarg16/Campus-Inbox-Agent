from datetime import datetime

import pytest

from app.rules import canonicalize_branch, evaluate
from app.schemas import FieldIssue, Profile, RuleStatus, Verdict

from .helpers import ev, make_extraction

NOW = datetime(2026, 10, 7, 12, 0)


def profile(**kw):
    base = dict(batch=2027, cgpa=8.4, branch="CSE", tenth_percent=92, twelfth_percent=88,
                active_backlogs=0, skills=["Python", "SQL"])
    base.update(kw)
    return Profile(**base)


def status_of(decision, rule):
    return next(r.status for r in decision.rules if r.rule == rule)


# --- the worked example from the plan ---------------------------------------------------------

def test_plan_example_is_eligible_with_evidence():
    ex = make_extraction(
        batches=ev([2027, 2028], "Batch 2027 and 2028 only."),
        min_cgpa=ev(8.0, "Minimum CGPA 8.0."),
        deadline=ev("2026-10-20T17:00", "Last date: 20 Oct, 5 PM."),
    )
    d = evaluate(ex, profile(), now=NOW)
    assert d.verdict is Verdict.ELIGIBLE
    assert {r.evidence for r in d.rules} == {"Batch 2027 and 2028 only.", "Minimum CGPA 8.0."}
    assert d.deadline_passed is False


def test_vague_academic_requirement_needs_review():
    ex = make_extraction(other_criteria=[ev("strong academics", "strong academics required")])
    d = evaluate(ex, profile(), now=NOW)
    assert d.verdict is Verdict.NEEDS_REVIEW


# --- batch -------------------------------------------------------------------------------------

def test_batch_not_listed_fails():
    d = evaluate(make_extraction(batches=ev([2025, 2026], "2025 and 2026 batch")), profile(), now=NOW)
    assert d.verdict is Verdict.NOT_ELIGIBLE
    assert "2027" in d.reasons[0]


def test_batch_missing_from_profile_is_unknown():
    d = evaluate(make_extraction(batches=ev([2027], "Batch 2027")), profile(batch=None), now=NOW)
    assert status_of(d, "batches") is RuleStatus.UNKNOWN
    assert d.verdict is Verdict.NEEDS_REVIEW


# --- CGPA --------------------------------------------------------------------------------------

@pytest.mark.parametrize("cgpa, expected", [
    (8.5, RuleStatus.PASS),   # exactly at the cutoff
    (8.49, RuleStatus.FAIL),
    (9.1, RuleStatus.PASS),
])
def test_cgpa_cutoff(cgpa, expected):
    ex = make_extraction(min_cgpa=ev(8.5, "register only if you're 8.5+ out of 10"))
    assert status_of(evaluate(ex, profile(cgpa=cgpa), now=NOW), "min_cgpa") is expected


def test_cgpa_float_noise_at_cutoff_passes():
    ex = make_extraction(min_cgpa=ev(0.3, "min CGPA 0.3"), cgpa_scale=10)
    assert status_of(evaluate(ex, profile(cgpa=0.1 + 0.2), now=NOW), "min_cgpa") is RuleStatus.PASS


def test_cgpa_scale_mismatch_is_unknown_not_guessed():
    ex = make_extraction(min_cgpa=ev(3.0, "Minimum GPA 3.0 on a 4 point scale"), cgpa_scale=4)
    d = evaluate(ex, profile(cgpa=6.0), now=NOW)
    assert status_of(d, "min_cgpa") is RuleStatus.UNKNOWN


def test_cgpa_or_equivalent_turns_fail_into_unknown():
    ex = make_extraction(min_cgpa=ev(8.5, "CGPA 8.5 or equivalent percentage"))
    d = evaluate(ex, profile(cgpa=8.0), now=NOW)
    assert status_of(d, "min_cgpa") is RuleStatus.UNKNOWN
    assert d.verdict is Verdict.NEEDS_REVIEW


def test_hedge_does_not_affect_a_pass():
    ex = make_extraction(min_cgpa=ev(7.0, "CGPA 7.0 preferred"))
    assert status_of(evaluate(ex, profile(cgpa=8.0), now=NOW), "min_cgpa") is RuleStatus.PASS


def test_cgpa_missing_in_profile_is_unknown():
    ex = make_extraction(min_cgpa=ev(7.0, "Minimum CGPA 7.0"))
    assert status_of(evaluate(ex, profile(cgpa=None), now=NOW), "min_cgpa") is RuleStatus.UNKNOWN


# --- 10th / 12th / backlogs ----------------------------------------------------------------------

def test_tenth_and_twelfth_minimums():
    ex = make_extraction(
        min_10th_percent=ev(90, "90% in 10th"),
        min_12th_percent=ev(90, "90% in 12th"),
    )
    d = evaluate(ex, profile(tenth_percent=92, twelfth_percent=88), now=NOW)
    assert status_of(d, "min_10th_percent") is RuleStatus.PASS
    assert status_of(d, "min_12th_percent") is RuleStatus.FAIL
    assert d.verdict is Verdict.NOT_ELIGIBLE


@pytest.mark.parametrize("mine, allowed, expected", [
    (0, 0, RuleStatus.PASS), (1, 0, RuleStatus.FAIL), (1, 1, RuleStatus.PASS), (None, 0, RuleStatus.UNKNOWN),
])
def test_backlogs(mine, allowed, expected):
    ex = make_extraction(max_active_backlogs=ev(allowed, "No active backlogs allowed / max 1"))
    assert status_of(evaluate(ex, profile(active_backlogs=mine), now=NOW), "max_active_backlogs") is expected


# --- branch ------------------------------------------------------------------------------------

@pytest.mark.parametrize("name, canon", [
    ("CSE", {"CSE"}),
    ("Computer Science and Engineering", {"CSE"}),
    ("Computer Science & Engineering", {"CSE"}),
    ("B.Tech CSE", {"CSE"}),
    ("Information Technology", {"IT"}),
    ("Electronics and Communication Engineering", {"ECE"}),
    ("All branches", {"ALL"}),
    ("Circuit branches", {"CSE", "IT", "ECE", "EEE", "EE"}),
    ("Underwater Basket Weaving", None),
])
def test_branch_canonicalization(name, canon):
    result = canonicalize_branch(name)
    assert (set(result) if result else None) == canon


def test_branch_alias_match_passes():
    ex = make_extraction(branches=ev(["Computer Science & Engineering", "IT"], "Open to CSE and IT"))
    assert status_of(evaluate(ex, profile(branch="CSE"), now=NOW), "branches") is RuleStatus.PASS


def test_all_branches_passes():
    ex = make_extraction(branches=ev(["All branches"], "Open to all branches"))
    assert status_of(evaluate(ex, profile(branch="Mechanical"), now=NOW), "branches") is RuleStatus.PASS


def test_known_branch_not_listed_fails():
    ex = make_extraction(branches=ev(["CSE", "IT"], "Branches: CSE, IT"))
    assert status_of(evaluate(ex, profile(branch="Mechanical Engineering"), now=NOW), "branches") is RuleStatus.FAIL


def test_unrecognised_branch_name_is_unknown_not_fail():
    ex = make_extraction(branches=ev(["CSE", "Engineering Physics"], "CSE, Engineering Physics"))
    assert status_of(evaluate(ex, profile(branch="Mechanical"), now=NOW), "branches") is RuleStatus.UNKNOWN


def test_unrecognised_profile_branch_matches_by_exact_text():
    ex = make_extraction(branches=ev(["Mathematics and Computing"], "Mathematics and Computing only"))
    d = evaluate(ex, profile(branch="mathematics & computing"), now=NOW)
    assert status_of(d, "branches") is RuleStatus.PASS


# --- skills ------------------------------------------------------------------------------------

def test_skills_present_pass_case_insensitive():
    ex = make_extraction(required_skills=ev(["python", "sql"], "Skills: Python, SQL"))
    assert status_of(evaluate(ex, profile(), now=NOW), "required_skills") is RuleStatus.PASS


def test_missing_skill_is_unknown_never_fail():
    ex = make_extraction(required_skills=ev(["Go"], "Knowledge of Go"))
    d = evaluate(ex, profile(), now=NOW)
    assert status_of(d, "required_skills") is RuleStatus.UNKNOWN
    assert d.verdict is Verdict.NEEDS_REVIEW


# --- verdict combination -----------------------------------------------------------------------

def test_fail_beats_unknown():
    ex = make_extraction(batches=ev([2025], "2025 batch only"), other_criteria=[ev("x", "good communication")])
    assert evaluate(ex, profile(), now=NOW).verdict is Verdict.NOT_ELIGIBLE


def test_no_criteria_needs_review():
    d = evaluate(make_extraction(company=ev("Acme", "Acme is hiring")), profile(), now=NOW)
    assert d.verdict is Verdict.NEEDS_REVIEW
    assert "No eligibility criteria" in d.reasons[0]


def test_rejected_eligibility_field_needs_review():
    ex = make_extraction(batches=ev([2027], "Batch 2027"))
    issues = [FieldIssue(field="min_cgpa", reason="evidence quote not found in the email", value=9.0)]
    d = evaluate(ex, profile(), issues=issues, now=NOW)
    assert d.verdict is Verdict.NEEDS_REVIEW
    assert status_of(d, "min_cgpa") is RuleStatus.UNKNOWN


def test_rejected_deadline_adds_unclear_note():
    issues = [FieldIssue(field="deadline", reason="not found")]
    d = evaluate(make_extraction(batches=ev([2027], "Batch 2027")), profile(), issues=issues, now=NOW)
    assert d.verdict is Verdict.ELIGIBLE  # deadline doesn't change eligibility
    assert any("Deadline unclear" in n for n in d.notes)


def test_not_an_opportunity_is_never_eligible():
    ex = make_extraction(is_opportunity=False, batches=ev([2027], "Batch 2027 results announced"))
    assert evaluate(ex, profile(), now=NOW).verdict is Verdict.NEEDS_REVIEW


def test_deadline_passed():
    ex = make_extraction(batches=ev([2027], "Batch 2027"), deadline=ev("2026-10-01T17:00", "Last date 1 Oct"))
    d = evaluate(ex, profile(), now=NOW)
    assert d.deadline_passed is True
    assert "The deadline has passed." in d.notes


def test_spans_are_attached():
    ex = make_extraction(batches=ev([2027], "Batch 2027"))
    d = evaluate(ex, profile(), spans={"batches": (10, 20)}, now=NOW)
    assert d.rules[0].span == (10, 20)


def test_profile_branch_alias_passes():
    ex = make_extraction(branches=ev(["Mathematics and Computing"], "Mathematics and Computing only"))
    p = profile(branch="MnC Dept", branch_aliases=["Mathematics & Computing"])
    assert status_of(evaluate(ex, p, now=NOW), "branches") is RuleStatus.PASS


def test_specialisation_vs_parent_branch_is_unknown_not_fail():
    ex = make_extraction(branches=ev(["CSE"], "Only CSE students"))
    assert status_of(evaluate(ex, profile(branch="CSE (AI&ML)"), now=NOW), "branches") is RuleStatus.UNKNOWN


def test_specialisation_alias_turns_into_pass():
    ex = make_extraction(branches=ev(["CSE"], "Only CSE students"))
    p = profile(branch="CSE (AI&ML)", branch_aliases=["CSE"])
    assert status_of(evaluate(ex, p, now=NOW), "branches") is RuleStatus.PASS


@pytest.mark.parametrize("name, canon", [
    ("Mathematics and Computing", {"MNC"}),
    ("Electronics & Instrumentation Engineering", {"EIE"}),
    ("Biotechnology", {"BT"}),
])
def test_more_branch_aliases(name, canon):
    assert set(canonicalize_branch(name)) == canon
