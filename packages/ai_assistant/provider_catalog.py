from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class AIProviderPreset(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    provider: str
    label: str
    base_url: str
    models_path: str = "/models"
    chat_path: str = "/chat/completions"
    api_key_hint: str
    recommended_models: list[str] = Field(default_factory=list)
    notes: str | None = None


PROVIDER_PRESETS: dict[str, AIProviderPreset] = {
    "openai": AIProviderPreset(
        provider="openai",
        label="OpenAI",
        base_url="https://api.openai.com/v1",
        api_key_hint="sk-...",
        recommended_models=["gpt-4.1", "gpt-4.1-mini", "gpt-4o", "gpt-4o-mini"],
    ),
    "openrouter": AIProviderPreset(
        provider="openrouter",
        label="OpenRouter",
        base_url="https://openrouter.ai/api/v1",
        api_key_hint="sk-or-...",
        recommended_models=[
            "openai/gpt-4.1",
            "anthropic/claude-sonnet-4",
            "google/gemini-2.5-pro",
            "deepseek/deepseek-chat",
        ],
        notes="OpenRouter can proxy many mainstream models through an OpenAI-compatible API.",
    ),
    "deepseek": AIProviderPreset(
        provider="deepseek",
        label="DeepSeek",
        base_url="https://api.deepseek.com",
        api_key_hint="sk-...",
        recommended_models=["deepseek-chat", "deepseek-reasoner"],
    ),
    "qwen": AIProviderPreset(
        provider="qwen",
        label="Qwen / DashScope",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key_hint="sk-...",
        recommended_models=["qwen-plus", "qwen-max", "qwen-turbo"],
    ),
    "moonshot": AIProviderPreset(
        provider="moonshot",
        label="Moonshot / Kimi",
        base_url="https://api.moonshot.cn/v1",
        api_key_hint="sk-...",
        recommended_models=["moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k"],
    ),
    "zhipu": AIProviderPreset(
        provider="zhipu",
        label="Zhipu GLM",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        api_key_hint="...",
        recommended_models=["glm-4", "glm-4-air", "glm-4-flash"],
    ),
    "groq": AIProviderPreset(
        provider="groq",
        label="Groq",
        base_url="https://api.groq.com/openai/v1",
        api_key_hint="gsk_...",
        recommended_models=["llama-3.3-70b-versatile", "llama-3.1-8b-instant"],
    ),
    "mistral": AIProviderPreset(
        provider="mistral",
        label="Mistral",
        base_url="https://api.mistral.ai/v1",
        api_key_hint="...",
        recommended_models=["mistral-large-latest", "mistral-small-latest"],
    ),
    "together": AIProviderPreset(
        provider="together",
        label="Together AI",
        base_url="https://api.together.xyz/v1",
        api_key_hint="...",
        recommended_models=["meta-llama/Llama-3.3-70B-Instruct-Turbo"],
    ),
    "siliconflow": AIProviderPreset(
        provider="siliconflow",
        label="SiliconFlow",
        base_url="https://api.siliconflow.cn/v1",
        api_key_hint="sk-...",
        recommended_models=["deepseek-ai/DeepSeek-V3", "Qwen/Qwen2.5-72B-Instruct"],
    ),
    "volcengine": AIProviderPreset(
        provider="volcengine",
        label="Volcengine Ark",
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        api_key_hint="...",
        recommended_models=[],
        notes="Model IDs are usually deployment or endpoint IDs configured in Ark.",
    ),
    "baichuan": AIProviderPreset(
        provider="baichuan",
        label="Baichuan",
        base_url="https://api.baichuan-ai.com/v1",
        api_key_hint="sk-...",
        recommended_models=["Baichuan4"],
    ),
    "stepfun": AIProviderPreset(
        provider="stepfun",
        label="StepFun",
        base_url="https://api.stepfun.com/v1",
        api_key_hint="...",
        recommended_models=["step-2-16k", "step-1-8k"],
    ),
    "minimax": AIProviderPreset(
        provider="minimax",
        label="MiniMax",
        base_url="https://api.minimax.chat/v1",
        api_key_hint="...",
        recommended_models=["abab6.5s-chat", "abab6.5-chat"],
    ),
    "custom": AIProviderPreset(
        provider="custom",
        label="Custom OpenAI-compatible",
        base_url="",
        api_key_hint="Enter provider API key",
        recommended_models=[],
        notes="Use this for any provider exposing /chat/completions and /models.",
    ),
}


def list_provider_presets() -> list[AIProviderPreset]:
    return list(PROVIDER_PRESETS.values())


def get_provider_preset(provider: str) -> AIProviderPreset | None:
    return PROVIDER_PRESETS.get(provider)
