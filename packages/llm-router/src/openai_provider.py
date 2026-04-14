"""OpenAI provider implementation."""

from typing import Any

from .providers import BaseLLMProvider, LLMResponse


class OpenAIProvider(BaseLLMProvider):
    """OpenAI API provider."""

    OPENAI_MODELS = {
        "gpt-4o",
        "gpt-4o-mini",
        "gpt-4-turbo",
        "gpt-4",
        "gpt-3.5-turbo",
    }

    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        super().__init__(api_key, base_url)
        self.base_url = base_url or "https://api.openai.com/v1"

    def supports_model(self, model: str) -> bool:
        return model in self.OPENAI_MODELS or model.startswith("gpt")

    async def complete(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        **kwargs
    ) -> LLMResponse:
        """Generate completion via OpenAI API."""
        import os
        import httpx

        api_key = self.api_key or os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY not provided")

        model = model or "gpt-4o"

        headers = {
            "Authorization": f"Bearer {api_key}",
            "content-type": "application/json",
        }

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": kwargs.get("max_tokens", 4096),
        }

        if "temperature" in kwargs:
            payload["temperature"] = kwargs["temperature"]

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=kwargs.get("timeout", 60.0),
            )
            response.raise_for_status()
            data = response.json()

        return LLMResponse(
            content=data["choices"][0]["message"]["content"],
            model=data["model"],
            provider="openai",
            usage={
                "prompt_tokens": data["usage"]["prompt_tokens"],
                "completion_tokens": data["usage"]["completion_tokens"],
            },
            raw_response=data,
        )