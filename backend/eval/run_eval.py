"""Run the extraction + rules pipeline over a labeled set and report accuracy.

Live (calls Gemini, saves predictions so you can re-score without paying again):
    python -m eval.run_eval --data eval/data/synthetic.jsonl
Re-score saved predictions:
    python -m eval.run_eval --data eval/data/synthetic.jsonl --replay eval/out/predictions.jsonl

Label format (one JSON object per line):
    {"id": "...", "received_at": "2026-10-07T09:00", "text": "...",
     "expected_opportunities": [{"company": ..., "deadline": "2026-10-20T17:00", ..., "verdict": "eligible"}]}

Report only numbers from data you did not tune the prompt on.
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from app.config import Settings
from app.extractor import ExtractionFailed, extract
from app.parsing import clean_text
from app.rules import evaluate
from app.schemas import Extraction, FieldIssue, Profile

from .scoring import FIELDS, score, to_markdown

HERE = Path(__file__).parent


def load_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _received(rec: dict) -> datetime | None:
    return datetime.fromisoformat(rec["received_at"]) if rec.get("received_at") else None


def _predict_one(settings: Settings, rec: dict) -> dict:
    client = settings.gemini_client()  # one client per thread
    try:
        outcome = extract(client, clean_text(rec["text"]), _received(rec))
        result = {"id": rec["id"], "attempts": outcome.attempts, "error": None, "opportunities": [
            {"extraction": o.extraction.model_dump(mode="json"),
             "issues": [i.model_dump(mode="json") for i in o.issues]}
            for o in outcome.opportunities
        ]}
    except Exception as e:  # ExtractionFailed, or the API giving up after retries
        attempts = len(getattr(e, "raw_responses", []))
        result = {"id": rec["id"], "attempts": attempts, "error": f"{type(e).__name__}: {e}"[:500], "opportunities": []}
    print(f"{rec['id']}: {'ok' if result['error'] is None else 'FAILED'}", file=sys.stderr, flush=True)
    return result


def predict(records: list[dict], workers: int = 8) -> list[dict]:
    settings = Settings.from_env()
    if not settings.gemini_api_key:
        sys.exit("GEMINI_API_KEY is not set. Use --replay to score saved predictions instead.")
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(lambda rec: _predict_one(settings, rec), records))


def expected_opportunities(rec: dict) -> list[dict]:
    items = rec.get("expected_opportunities")
    if items is None:  # older single-opportunity format
        items = [{**rec["expected"], "verdict": rec.get("expected_verdict")}]
    return [{"fields": {f: item.get(f) for f in FIELDS}, "verdict": item.get("verdict")} for item in items]


def build_scoring_records(records: list[dict], predictions: list[dict], profile: Profile) -> list[dict]:
    by_id = {p["id"]: p for p in predictions}
    rows = []
    for rec in records:
        pred = by_id.get(rec["id"])
        failed = pred is None or bool(pred.get("error"))
        predicted = []
        for item in ([] if failed else pred["opportunities"]):
            ex = Extraction.model_validate(item["extraction"])
            issues = [FieldIssue.model_validate(i) for i in item["issues"]]
            predicted.append({
                "fields": {f: item["extraction"][f]["value"] for f in FIELDS},
                "verdict": evaluate(ex, profile, issues, now=_received(rec)).verdict.value,
            })
        rows.append({"id": rec["id"], "failed": failed, "expected": expected_opportunities(rec),
                     "predicted": predicted})
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, default=HERE / "data" / "synthetic.jsonl")
    ap.add_argument("--profile", type=Path, default=HERE / "data" / "eval_profile.json")
    ap.add_argument("--replay", type=Path, help="score saved predictions instead of calling the LLM")
    ap.add_argument("--out", type=Path, default=HERE / "out")
    ap.add_argument("--workers", type=int, default=8, help="emails processed in parallel")
    ap.add_argument("--retry-failed", action="store_true",
                    help="re-run only emails that failed in out/predictions.jsonl (e.g. after a quota error)")
    args = ap.parse_args()

    records = load_jsonl(args.data)
    profile = Profile.model_validate_json(args.profile.read_text(encoding="utf-8"))
    args.out.mkdir(parents=True, exist_ok=True)

    if args.replay:
        predictions = load_jsonl(args.replay)
    elif args.retry_failed:
        previous = load_jsonl(args.out / "predictions.jsonl")
        failed = {p["id"] for p in previous if p.get("error")}
        redone = {p["id"]: p for p in predict([r for r in records if r["id"] in failed], args.workers)}
        predictions = [redone.get(p["id"], p) for p in previous]
        with (args.out / "predictions.jsonl").open("w", encoding="utf-8") as f:
            for p in predictions:
                f.write(json.dumps(p) + "\n")
    else:
        predictions = predict(records, args.workers)
        with (args.out / "predictions.jsonl").open("w", encoding="utf-8") as f:
            for p in predictions:
                f.write(json.dumps(p) + "\n")

    report = to_markdown(score(build_scoring_records(records, predictions, profile)))
    (args.out / "report.md").write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
