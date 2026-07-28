import pytest
from pydantic import ValidationError

from apps.api.services.hermes_diagnostic_service import (
    HermesDiagnosticSuggestionPayload,
    _validate_hermes_suggestion,
)


def test_hermes_parser_accepts_wrapped_nested_json_and_trailing_comma() -> None:
    payload = _validate_hermes_suggestion(
        """
        <think>private reasoning with {"not":"the answer"}</think>
        诊断结果：
        ```json
        {
          "suggested_action": "manual_review",
          "can_auto_correct": false,
          "confidence": 77,
          "reason_zh": "证据不足。",
          "evidence_ids": ["zone_rule:R3A"],
        }
        ```
        """
    )

    assert payload.suggested_action == "manual_review"
    assert payload.can_auto_correct is False
    assert payload.confidence == 77


def test_hermes_model_output_is_sanitized_to_advisory_only() -> None:
    payload = _validate_hermes_suggestion(
        """
        {
          "suggested_action": "manual_review",
          "can_auto_correct": true,
          "confidence": "91%",
          "reason_zh": "建议人工确认。",
          "suggested_price_usd": "999.00"
        }
        """
    )

    assert payload.can_auto_correct is False
    assert payload.confidence == 91
    assert "suggested_price_usd" not in payload.model_dump()


def test_public_suggestion_contract_rejects_auto_correction() -> None:
    with pytest.raises(ValidationError):
        HermesDiagnosticSuggestionPayload.model_validate(
            {
                "can_auto_correct": True,
                "reason_zh": "不允许自动纠错。",
            }
        )
