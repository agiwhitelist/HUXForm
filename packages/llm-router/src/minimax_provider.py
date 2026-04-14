"""MiniMax LLM provider - Anthropic-compatible API."""

import os
from typing import Any

from .providers import BaseLLMProvider, LLMResponse


class MiniMaxProvider(BaseLLMProvider):
    """MiniMax provider using Anthropic-compatible API."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = "https://api.minimax.io/anthropic/v1",
    ):
        super().__init__(api_key=api_key, base_url=base_url)
        self._api_key = api_key or os.environ.get("ANTHROPIC_AUTH_TOKEN", "")
        self._base_url = base_url

    def supports_model(self, model: str) -> bool:
        """MiniMax supports various models via Anthropic compatibility."""
        return True  # MiniMax gateway is flexible

    async def complete(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        **kwargs
    ) -> LLMResponse:
        """Generate completion via MiniMax Anthropic-compatible API."""
        import anthropic

        # Use MiniMax's model mapping
        model = model or "MiniMax-M2.7"

        client = anthropic.Anthropic(
            api_key=self._api_key,
            base_url=self._base_url,
        )

        response = client.messages.create(
            model=model,
            max_tokens=kwargs.get("max_tokens", 4096),
            messages=messages,
            temperature=kwargs.get("temperature", 0.7),
        )

        # Handle MiniMax response which may include ThinkingBlock
        text_content = ""
        thinking_content = ""
        for block in response.content:
            if hasattr(block, 'text') and block.text:
                text_content += block.text
            elif hasattr(block, 'thinking') and block.thinking:
                thinking_content = block.thinking

        # Return text content (or thinking if no text)
        final_content = text_content if text_content else thinking_content

        return LLMResponse(
            content=final_content,
            model=model,
            provider="minimax",
            usage={
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            },
            raw_response=response.model_dump(),
        )
