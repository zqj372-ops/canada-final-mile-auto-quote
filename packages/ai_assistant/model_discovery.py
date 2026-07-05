from __future__ import annotations

from time import perf_counter
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

from packages.ai_assistant.provider_catalog import get_provider_preset


class DiscoveredModel(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    id: str
    display_name: str | None = None
    owned_by: str | None = None
    context_length: int | None = None
    source: str = "provider"


class ModelDiscoveryResult(BaseModel):
    provider: str
    base_url: str
    models: list[DiscoveredModel] = Field(default_factory=list)
    latency_ms: int | None = None
    error: str | None = None


def discover_models(
    *,
    provider: str,
    api_key: str,
    base_url: str | None = None,
    timeout_seconds: int = 20,
) -> ModelDiscoveryResult:
    preset = get_provider_preset(provider)
    resolved_base_url = (base_url or preset.base_url if preset else base_url or "").rstrip("/")
    result = ModelDiscoveryResult(provider=provider, base_url=resolved_base_url)
    if not resolved_base_url:
        result.error = "base_url is required for model discovery."
        return result
    if not api_key:
        result.error = "api_key is required for model discovery."
        return result

    models_url = _join_url(resolved_base_url, preset.models_path if preset else "/models")
    started = perf_counter()
    try:
        with httpx.Client(timeout=timeout_seconds) as client:
            response = client.get(
                models_url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
            )
        result.latency_ms = int((perf_counter() - started) * 1000)
        if response.status_code >= 400:
            result.error = f"Provider returned HTTP {response.status_code}: {_safe_error_body(response.text)}"
            return result

        result.models = _parse_models(response.json())
        if not result.models and preset and preset.recommended_models:
            result.models = [
                DiscoveredModel(id=model_id, display_name=model_id, source="recommended")
                for model_id in preset.recommended_models
            ]
            result.error = "Provider returned no model list; showing preset recommended models."
        return result
    except Exception as exc:
        result.latency_ms = int((perf_counter() - started) * 1000)
        result.error = f"{exc.__class__.__name__}: {exc}"
        return result


def _parse_models(data: Any) -> list[DiscoveredModel]:
    raw_models: Any
    if isinstance(data, dict):
        raw_models = data.get("data") or data.get("models") or data.get("items") or []
    else:
        raw_models = data

    if not isinstance(raw_models, list):
        return []

    models: list[DiscoveredModel] = []
    for item in raw_models:
        if isinstance(item, str):
            models.append(DiscoveredModel(id=item, display_name=item))
            continue
        if not isinstance(item, dict):
            continue
        model_id = item.get("id") or item.get("name") or item.get("model")
        if not isinstance(model_id, str) or not model_id.strip():
            continue
        display_name = item.get("name") or item.get("display_name") or model_id
        context_length = item.get("context_length") or item.get("context_window")
        models.append(
            DiscoveredModel(
                id=model_id,
                display_name=display_name if isinstance(display_name, str) else model_id,
                owned_by=item.get("owned_by") if isinstance(item.get("owned_by"), str) else None,
                context_length=context_length if isinstance(context_length, int) else None,
            )
        )
    return sorted({model.id: model for model in models}.values(), key=lambda model: model.id)


def _join_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _safe_error_body(text: str) -> str:
    compact = " ".join(text.split())
    if len(compact) > 300:
        return compact[:300] + "..."
    return compact
