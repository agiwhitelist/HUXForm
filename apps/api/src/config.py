"""Runtime configuration loaded from environment variables.

AGUI is provider-agnostic. By default we talk to MiniMax M2.7 via its
Anthropic-compatible endpoint, but any provider speaking either the
Anthropic Messages or OpenAI Chat Completions protocol will work — just
point AGUI_LLM_BASE_URL at it and pick the protocol via
AGUI_LLM_PROTOCOL.
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
        base_url = _env("AGUI_LLM_BASE_URL", "https://api.minimax.io/anthropic") or ""
        api_key = _env("AGUI_LLM_API_KEY") or _env("ANTHROPIC_AUTH_TOKEN") or _env("ANTHROPIC_API_KEY") or _env("MINIMAX_API_KEY") or ""
        model = _env("AGUI_LLM_MODEL", "MiniMax-M2") or "MiniMax-M2"
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
