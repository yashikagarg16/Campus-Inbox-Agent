"""Score guarded extractions and verdicts against hand labels.

Each field gets one outcome:
- correct:  matches the label (including both empty)
- missed:   label has a value, system said nothing (safe: shows up as "needs review")
- wrong:    system gave a different value (dangerous)
- spurious: label is empty, system invented a value (dangerous)

Emails can hold several opportunities. Predicted ones are matched to labeled ones by
company name (or directly when there is exactly one of each). A labeled opportunity
with no match is "missed"; a predicted one with no label is "spurious".
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any

from app.rules import _branch_key, canonicalize_branch

FIELDS = ("company", "role", "deadline", "form_link", "batches", "min_cgpa", "branches",
          "min_10th_percent", "min_12th_percent", "max_active_backlogs")


def _branch_set(names: list[str]) -> set[str]:
    out: set[str] = set()
    for n in names:
        out |= canonicalize_branch(n) or {_branch_key(n)}
    return out


def values_equal(field: str, expected: Any, predicted: Any) -> bool:
    if field in ("company", "role"):
        a, b = expected.strip().casefold(), predicted.strip().casefold()
        return a == b or a in b or b in a
    if field == "deadline":
        return datetime.fromisoformat(expected) == datetime.fromisoformat(predicted)
    if field == "form_link":
        return expected.rstrip("/") == predicted.rstrip("/")
    if field == "batches":
        return set(expected) == set(predicted)
    if field == "branches":
        return _branch_set(expected) == _branch_set(predicted)
    return abs(float(expected) - float(predicted)) < 1e-6


def field_outcome(field: str, expected: Any, predicted: Any) -> str:
    if expected is None and predicted is None:
        return "correct"
    if expected is None:
        return "spurious"
    if predicted is None:
        return "missed"
    return "correct" if values_equal(field, expected, predicted) else "wrong"


def verdict_outcome(expected: str, predicted: str | None) -> str:
    if predicted is None:
        return "missed"  # the opportunity never reached the dashboard
    if expected == predicted:
        return "correct"
    if predicted == "needs_review":
        return "abstained"  # safe: the user is told to check
    return "wrong"  # e.g. said eligible when not: the dangerous case


def match_opportunities(expected: list[dict], predicted: list[dict]) -> tuple[list[tuple[dict, dict | None]], int]:
    """Pair labeled and predicted opportunities. Returns (pairs, number of unmatched predictions)."""
    if len(expected) == 1 and len(predicted) == 1:
        return [(expected[0], predicted[0])], 0
    remaining = list(range(len(predicted)))
    pairs = []
    for exp in expected:
        company = exp["fields"].get("company")
        j = next((j for j in remaining if company and predicted[j]["fields"].get("company")
                  and values_equal("company", company, predicted[j]["fields"]["company"])), None)
        if j is not None:
            remaining.remove(j)
        pairs.append((exp, predicted[j] if j is not None else None))
    return pairs, len(remaining)


def score(records: list[dict]) -> dict:
    """records: [{"id", "failed": bool,
                  "expected": [{"fields": {...}, "verdict": str}],
                  "predicted": [{"fields": {...}, "verdict": str}]}]"""
    fields = {f: Counter() for f in FIELDS}
    verdicts: Counter = Counter()
    opportunities: Counter = Counter()
    failures = []
    n_opps = 0
    for rec in records:
        pairs, spurious = match_opportunities(rec["expected"], rec["predicted"])
        opportunities["spurious"] += spurious
        if spurious:
            failures.append({"id": rec["id"], "field": "opportunities", "outcome": "spurious",
                             "expected": len(rec["expected"]), "predicted": len(rec["predicted"])})
        for exp, pred in pairs:
            n_opps += 1
            opportunities["matched" if pred else ("failed" if rec.get("failed") else "missed")] += 1
            pred_fields = pred["fields"] if pred else {}
            for f in FIELDS:
                o = field_outcome(f, exp["fields"].get(f), pred_fields.get(f))
                fields[f][o] += 1
                if o != "correct":
                    failures.append({"id": rec["id"], "field": f, "outcome": o,
                                     "expected": exp["fields"].get(f), "predicted": pred_fields.get(f)})
            if exp.get("verdict"):
                # A failed extraction is shown to the user as failed, so it counts as abstaining.
                predicted_verdict = pred["verdict"] if pred else ("needs_review" if rec.get("failed") else None)
                o = verdict_outcome(exp["verdict"], predicted_verdict)
                verdicts[o] += 1
                if o != "correct":
                    failures.append({"id": rec["id"], "field": "verdict", "outcome": o,
                                     "expected": exp["verdict"], "predicted": predicted_verdict})
    return {"n_emails": len(records), "n": n_opps, "fields": fields, "verdicts": verdicts,
            "opportunities": opportunities, "failures": failures}


def to_markdown(result: dict) -> str:
    n = result["n"]
    o = result["opportunities"]
    lines = [f"# Eval report ({result['n_emails']} emails, {n} labeled opportunities)", "",
             f"Opportunities: {o['matched']} found, {o['missed']} missed, {o['failed']} in failed extractions, "
             f"{o['spurious']} invented.", "",
             "| field | correct | missed | wrong | spurious | accuracy |", "|---|---|---|---|---|---|"]
    for f, c in result["fields"].items():
        acc = c["correct"] / n if n else 0
        lines.append(f"| {f} | {c['correct']} | {c['missed']} | {c['wrong']} | {c['spurious']} | {acc:.0%} |")
    v = result["verdicts"]
    total = sum(v.values())
    lines += ["", "## Verdicts", "",
              f"- correct: {v['correct']}/{total}",
              f"- abstained (said needs review): {v['abstained']}/{total}",
              f"- missed (opportunity not found): {v['missed']}/{total}",
              f"- **wrong (confident and incorrect): {v['wrong']}/{total}**", "", "## Failures", ""]
    if not result["failures"]:
        lines.append("None.")
    for fl in result["failures"]:
        lines.append(f"- `{fl['id']}` {fl['field']}: {fl['outcome']} "
                     f"(expected `{fl['expected']}`, got `{fl['predicted']}`)")
    return "\n".join(lines) + "\n"
