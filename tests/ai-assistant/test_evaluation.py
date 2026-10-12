import json
from pathlib import Path

import pytest

from packages.ai_assistant.evaluation import EvaluationCase, load_cases, run_case, summarize


def case(**overrides):
    return {"id": "fixture-1", "group_id": "template-1", "split": "test", "source": "synthetic_fixture",
            "raw": "无需尾板", "expected_fields": {"requires_liftgate": False}, **overrides}


@pytest.mark.parametrize("second", [
    case(id="fixture-2", split="train", raw="需要尾板"),
    case(id="fixture-2", group_id="another", split="train"),
])
def test_rejects_group_and_identical_input_leakage(tmp_path, second):
    path = tmp_path / "cases.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in (case(), second)))
    with pytest.raises(ValueError, match="leakage"):
        load_cases(path)


def test_unknown_is_not_scored_as_false():
    row = run_case(EvaluationCase.model_validate(case(raw="尾板待确认", expected_fields={"requires_liftgate": None})), "local")
    assert row["prediction"]["requires_liftgate"] is None
    assert summarize([row])["unknown_preservation_rate"] == 1
    assert summarize([row])["model_calls"] == 0


def test_synthetic_conformance_is_labelled_and_network_free():
    cases = load_cases(Path(__file__).parents[1] / "fixtures/extraction/conformance.jsonl")
    rows = [run_case(item, "local") for item in cases]
    report = summarize(rows)
    assert report["source_counts"] == {"synthetic_fixture": 8}
    assert report["labelled_case_accuracy"] == 1
    assert report["model_calls"] == 0
    assert report["prompt_tokens"] is None


def test_extraction_error_does_not_count_as_preserving_unknown():
    row = run_case(EvaluationCase.model_validate(case(expected_fields={"requires_liftgate": None})), "dual")
    assert row["error"] is not None
    assert summarize([row])["unknown_preservation_rate"] == 0
