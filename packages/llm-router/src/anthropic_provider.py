"""Anthropic provider implementation."""

from typing import Any

from .providers import BaseLLMProvider, LLMResponse


class AnthropicProvider(BaseLLMProvider):
    """Anthropic Claude API provider."""

    ANTHROPIC_MODELS = {
        "claude-3-5-sonnet-latest",
        "claude-3-5-sonnet-20241022",
        "claude-3-opus-latest",
        "claude-3-opus-20240229",
        "claude-3-haiku-latest",
        "claude-3-haiku-20240307",
    }

    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        super().__init__(api_key, base_url)
        self.base_url = base_url or "https://api.anthropic.com"

    def supports_model(self, model: str) -> bool:
        return model in self.ANTHROPIC_MODELS or model.startswith("claude")

    async def complete(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        **kwargs
    ) -> LLMResponse:
        """Generate completion via Anthropic API."""
        import os
        import httpx

        api_key = self.api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY not provided")

        model = model or "claude-3-5-sonnet-latest"

        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": kwargs.get("max_tokens", 4096),
        }

        if "system" in kwargs:
            payload["system"] = kwargs["system"]

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/v1/messages",
                headers=headers,
                json=payload,
                timeout=kwargs.get("timeout", 60.0),
            )
            response.raise_for_status()
            data = response.json()

        return LLMResponse(
            content=data["content"][0]["text"],
            model=data["model"],
            provider="anthropic",
            usage={
                "input_tokens": data["usage"]["input_tokens"],
                "output_tokens": data["usage"]["output_tokens"],
            },
            raw_response=data,
        )