"""LLM Router with provider fallback."""

from typing import Any

from .providers import BaseLLMProvider, LLMResponse
from .anthropic_provider import AnthropicProvider
from .openai_provider import OpenAIProvider
from .minimax_provider import MiniMaxProvider
from .registry import ModelConfig, get_model_config


class LLMRouter:
    """Router that routes LLM requests to appropriate providers with fallback."""

    def __init__(self):
        self.providers: dict[str, BaseLLMProvider] = {
            "anthropic": AnthropicProvider(),
            "openai": OpenAIProvider(),
            "minimax": MiniMaxProvider(),
        }
        self._fallback_order = ["minimax", "anthropic", "openai"]

    def add_provider(self, name: str, provider: BaseLLMProvider) -> None:
        """Add a custom provider."""
        self.providers[name] = provider

    def set_fallback_order(self, order: list[str]) -> None:
        """Set the fallback order for providers."""
        self._fallback_order = order

    async def complete(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        **kwargs
    ) -> LLMResponse:
        """Route to appropriate provider with fallback."""
        model_config = get_model_config(model) if model else None
        provider_name = model_config.provider if model_config else None

        # Try specified provider first
        if provider_name and provider_name in self.providers:
            provider = self.providers[provider_name]
            if model and provider.supports_model(model):
                try:
                    return await provider.complete(messages, model, **kwargs)
                except Exception:
                    pass

        # Try fallback order
        for pname in self._fallback_order:
            if pname == provider_name:
                continue
            provider = self.providers.get(pname)
            if provider:
                try:
                    return await provider.complete(messages, model, **kwargs)
                except Exception:
                    continue

        raise RuntimeError("No available provider succeeded for completion")

    async def complete_with_fallback(
        self,
        messages: list[dict[str, str]],
        preferred_model: str | None = None,
        fallback_models: list[str] | None = None,
        **kwargs
    ) -> LLMResponse:
        """Try preferred model, fall back to alternatives on failure."""
        fallback_models = fallback_models or []

        # Try preferred first
        if preferred_model:
            try:
                return await self.complete(messages, preferred_model, **kwargs)
            except Exception:
                pass

        # Try fallbacks
        for model in fallback_models:
            try:
                return await self.complete(messages, model, **kwargs)
            except Exception:
                continue

        raise RuntimeError("All model attempts failed")