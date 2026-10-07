import json
from pathlib import Path

from eval.run_eval import build_scoring_records, expected_opportunities
from eval.scoring import field_outcome, match_opportunities, score, to_markdown, verdict_outcome

from app.schemas import Profile

from .helpers import SAMPLE_RESPONSE, ev


def test_field_outcomes():
    assert field_outcome("min_cgpa", None, None) == "correct"
    assert field_outcome("min_cgpa", 8.0, None) == "missed"
    assert field_outcome("min_cgpa", None, 8.0) == "spurious"
    assert field_outcome("min_cgpa", 8.0, 8.5) == "wrong"
    assert field_outcome("batches", [2028, 2027], [2027, 2028]) == "correct"
    assert field_outcome("branches", ["Computer Science and Engineering"], ["CSE"]) == "correct"
    assert field_outcome("deadline", "2026-10-20T17:00", "2026-10-20T17:00:00") == "correct"
    assert field_outcome("company", "Acme Analytics", "acme analytics pvt ltd") == "correct"


def test_verdict_outcomes():
    assert verdict_outcome("eligible", "eligible") == "correct"
    assert verdict_outcome("eligible", "needs_review") == "abstained"
    assert verdict_outcome("not_eligible", "eligible") == "wrong"
    assert verdict_outcome("eligible", None) == "missed"


def test_matching_by_company():
    exp = [{"fields": {"company": "Lumen"}}, {"fields": {"company": "Cedar Bank"}}]
    pred = [{"fields": {"company": "Cedar Bank Ltd"}}, {"fields": {"company": "Other"}}]
    pairs, spurious = match_opportunities(exp, pred)
    assert pairs[0][1] is None and pairs[1][1] is pred[0]
    assert spurious == 1


def test_replay_scoring_end_to_end():
    record = {"id": "x", "received_at": "2026-10-07T09:00",
              "expected": {"min_cgpa": 8.0, "batches": [2027, 2028]}, "expected_verdict": "eligible"}
    prediction = {"id": "x", "error": None, "opportunities": [{"extraction": SAMPLE_RESPONSE, "issues": []}]}
    profile = Profile(batch=2027, cgpa=8.4, branch="CSE")
    rows = build_scoring_records([record], [prediction], profile)
    assert rows[0]["predicted"][0]["verdict"] == "eligible"
    result = score(rows)
    assert result["fields"]["min_cgpa"]["correct"] == 1
    assert result["fields"]["company"]["spurious"] == 1  # label left company empty
    assert "# Eval report (1 emails, 1 labeled opportunities)" in to_markdown(result)


def test_failed_prediction_counts_as_abstained():
    record = {"id": "x", "expected_opportunities": [{"min_cgpa": 8.0, "verdict": "eligible"}]}
    rows = build_scoring_records([record], [{"id": "x", "error": "boom", "opportunities": []}], Profile())
    result = score(rows)
    assert result["verdicts"]["abstained"] == 1
    assert result["opportunities"]["failed"] == 1


def test_synthetic_labels_are_well_formed():
    path = Path(__file__).parent.parent / "eval" / "data" / "synthetic.jsonl"
    for line in path.read_text(encoding="utf-8").splitlines():
        rec = json.loads(line)
        assert rec["text"] and rec["id"]
        for opp in expected_opportunities(rec):
            assert opp["verdict"] in ("eligible", "not_eligible", "needs_review")
