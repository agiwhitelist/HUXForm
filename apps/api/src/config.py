"""Runtime configuration loaded from environment variables.

HUXForm is provider-agnostic. Any provider speaking either the
Anthropic Messages or OpenAI Chat Completions protocol works — just
point AGUI_LLM_BASE_URL at it, pick the protocol via AGUI_LLM_PROTOCOL,
and set AGUI_LLM_MODEL to whatever model id the provider exposes.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class LLMConfig:
    protocol: str          # "anthropic" | "openai"
    base_url: str
    api_key: str
    model: str
    max_tokens: int
    temperature: float


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value


def load_llm_config() -> LLMConfig:
    protocol = (_env("AGUI_LLM_PROTOCOL", "anthropic") or "anthropic").lower()

    if protocol == "anthropic":
        base_url = _env("AGUI_LLM_BASE_URL", "https://api.anthropic.com") or ""
        api_key = _env("AGUI_LLM_API_KEY") or _env("ANTHROPIC_API_KEY") or _env("ANTHROPIC_AUTH_TOKEN") or ""
        model = _env("AGUI_LLM_MODEL", "claude-opus-4-7") or "claude-opus-4-7"
    elif protocol == "openai":
        base_url = _env("AGUI_LLM_BASE_URL", "https://api.openai.com/v1") or ""
        api_key = _env("AGUI_LLM_API_KEY") or _env("OPENAI_API_KEY") or ""
        model = _env("AGUI_LLM_MODEL", "gpt-4o-mini") or "gpt-4o-mini"
    else:
        raise RuntimeError(f"Unsupported AGUI_LLM_PROTOCOL: {protocol!r} (expected 'anthropic' or 'openai')")

    return LLMConfig(
        protocol=protocol,
        base_url=base_url.rstrip("/"),
        api_key=api_key,
        model=model,
        max_tokens=int(_env("AGUI_LLM_MAX_TOKENS", "4096") or "4096"),
        temperature=float(_env("AGUI_LLM_TEMPERATURE", "0.6") or "0.6"),
    )
