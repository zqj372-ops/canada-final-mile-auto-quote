"""Offline extraction evaluation; labels and splits are explicit, never inferred."""
from collections import Counter
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
from pathlib import Path
from time import perf_counter
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from packages.ai_assistant.extraction_runtime import ObservedAIClient, submit_extraction
from packages.ai_assistant.fast_extractor import try_extract_locally
from packages.ai_assistant.quote_extractor import AIExtractedQuoteDraft, apply_deterministic_extraction, extract_quote_draft, extract_quote_draft_with_agents
from packages.quote_engine.zone_models import ZoneQuoteRequest


class EvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1)
    group_id: str = Field(min_length=1)
    split: Literal["train", "validation", "test"] = "test"
    source: Literal["synthetic_fixture", "operator_reviewed"]
    raw: str = Field(min_length=1, max_length=20000)
    expected_fields: dict[str, object]
    tolerances: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def known_fields(self):
        if not self.expected_fields or not set(self.expected_fields).issubset(ZoneQuoteRequest.model_fields):
            raise ValueError("expected_fields must contain known quote fields")
        if any(value < 0 for value in self.tolerances.values()):
            raise ValueError("tolerances must be nonnegative")
        return self


def load_cases(path: Path) -> list[EvaluationCase]:
    cases = [EvaluationCase.model_validate(json.loads(line)) for line in path.read_text().splitlines() if line.strip()]
    ids, group_splits, raw_splits = set(), {}, {}
    for case in cases:
        if case.id in ids:
            raise ValueError(f"Duplicate case id: {case.id}")
        ids.add(case.id)
        raw_hash = hashlib.sha256(" ".join(case.raw.split()).encode()).hexdigest()
        for key, registry in ((case.group_id, group_splits), (raw_hash, raw_splits)):
            if key in registry and registry[key] != case.split:
                raise ValueError("Data leakage: one group or identical input occurs in different splits")
            registry[key] = case.split
    return cases


def field_matches(field: str, actual: object, expected: object, tolerance: float = 0) -> bool:
    if expected is None or actual is None or isinstance(expected, bool):
        return type(actual) is type(expected) and actual == expected
    if field in {"cbm", "weight_kg", "piece_count", "longest_side_cm", "explicit_pallet_count", "detention_minutes"}:
        try:
            return abs(Decimal(str(actual)) - Decimal(str(expected))) <= Decimal(str(tolerance))
        except InvalidOperation:
            return False
    normalize = lambda value: " ".join(str(value).strip().upper().split())
    if field == "postal_code":
        return normalize(actual).replace(" ", "") == normalize(expected).replace(" ", "")
    return normalize(actual) == normalize(expected)


def run_case(case: EvaluationCase, strategy: str, *, client=None, budget_seconds: float = 30) -> dict:
    started = perf_counter()
    observer = ObservedAIClient(client, deadline=started + budget_seconds) if client else None
    prediction, error = {}, None
    try:
        if strategy == "local":
            draft = try_extract_locally(case.raw) or apply_deterministic_extraction(AIExtractedQuoteDraft(), case.raw)
        elif strategy == "single" and observer:
            future = submit_extraction(extract_quote_draft, case.raw, observer)
            try:
                draft = future.result(timeout=budget_seconds)
            finally:
                future.cancel()
        elif strategy == "dual" and observer:
            draft = extract_quote_draft_with_agents(case.raw, observer, deadline=observer.deadline)
        else:
            raise ValueError("Model strategies require an explicitly configured client")
        prediction = draft.model_dump(mode="json")
    except Exception as exc:
        error = type(exc).__name__
    fields = {field: error is None and field_matches(field, prediction.get(field), expected, case.tolerances.get(field, 0))
              for field, expected in case.expected_fields.items()}
    return {"id": case.id, "group_id": case.group_id, "source": case.source,
            "duration_ms": round((perf_counter() - started) * 1000), "error": error,
            "labelled_fields_correct": all(fields.values()), "field_results": fields,
            "unknown_fields": [field for field, expected in case.expected_fields.items() if expected is None],
            "prediction": {field: prediction.get(field) for field in case.expected_fields},
            **(observer.snapshot() if observer else {"model_calls": 0, "repair_calls": 0, "calls": []})}


def summarize(rows: list[dict]) -> dict:
    field_total, field_correct = Counter(), Counter()
    unknown_total = unknown_correct = 0
    for row in rows:
        for field, correct in row["field_results"].items():
            field_total[field] += 1
            field_correct[field] += int(correct)
        for field in row["unknown_fields"]:
            unknown_total += 1
            unknown_correct += int(row["field_results"][field])
    times = sorted(row["duration_ms"] for row in rows)
    percentile = lambda fraction: times[max(0, math.ceil(len(times) * fraction) - 1)] if times else None
    calls = [call for row in rows for call in row["calls"]]
    def tokens(key):
        values = [call.get(key) for call in calls]
        return sum(values) if values and all(isinstance(value, int) for value in values) else None
    return {"cases": len(rows), "source_counts": dict(Counter(row["source"] for row in rows)),
            "labelled_case_accuracy": sum(row["labelled_fields_correct"] for row in rows) / len(rows) if rows else None,
            "field_accuracy": {field: field_correct[field] / total for field, total in field_total.items()},
            "unknown_preservation_rate": unknown_correct / unknown_total if unknown_total else None,
            "p50_ms": percentile(.5), "p95_ms": percentile(.95),
            "failed_cases": sum(row["error"] is not None for row in rows),
            "model_calls": sum(row["model_calls"] for row in rows),
            "repair_calls": sum(row["repair_calls"] for row in rows),
            "prompt_tokens": tokens("prompt_tokens"), "completion_tokens": tokens("completion_tokens"),
            "scope": "Only explicitly labelled extraction fields; does not measure price correctness or production accuracy."}
