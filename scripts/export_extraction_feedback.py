"""Export reviewed correction fields from existing audits to a local JSONL dataset."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select
from apps.api.db.models import QuoteAuditLog
from apps.api.db.session import get_session_factory


def reviewed_cases(db, limit=1000):
    rows = db.scalars(select(QuoteAuditLog).where(
        QuoteAuditLog.request_json["extraction_feedback"]["status"].as_string() == "approved"
    ).order_by(QuoteAuditLog.id.desc()).limit(max(1, min(limit, 10000))))
    seen = set()
    for row in rows:
        request = row.request_json
        feedback = request["extraction_feedback"]
        if not feedback.get("verified_source") or feedback.get("run_id") in seen:
            continue
        expected = {item["field"]: item["after"] for item in feedback["corrections"]
                    if item["field"] in feedback["approved_fields"] and item["reason"] == "extraction_error"}
        if not expected or not feedback.get("evaluation_group"):
            continue
        seen.add(feedback["run_id"])
        yield {"id": feedback["run_id"], "group_id": feedback["evaluation_group"],
               "split": feedback.get("split", "test"), "source": "operator_reviewed",
               "raw": request["customer_message"], "expected_fields": expected}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=1000)
    args = parser.parse_args()
    with get_session_factory()() as db:
        cases = list(reviewed_cases(db, args.limit))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("".join(json.dumps(case, ensure_ascii=False) + "\n" for case in cases))
    print(f"Exported {len(cases)} reviewed cases. No model calls or database writes.")


if __name__ == "__main__":
    main()
