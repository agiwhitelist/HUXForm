"""Tiny provider-agnostic LLM client.

We deliberately do not depend on vendor SDKs. HUXForm's needs are simple:
send a system prompt + a list of role/content messages, get back text.
We support the two protocols that nearly every provider speaks:

  * Anthropic Messages API  (POST /v1/messages)        — Anthropic, MiniMax
  * OpenAI Chat Completions (POST /v1/chat/completions) — OpenAI, OpenRouter,
                                                          Groq, Together, ...

Pick one with AGUI_LLM_PROTOCOL and point AGUI_LLM_BASE_URL at the host.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, AsyncIterator

import httpx

from .config import LLMConfig, load_llm_config


@dataclass
class LLMReply:
    text: str
    raw: dict[str, Any]
    usage: dict[str, int] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.usage is None:
            u = (self.raw or {}).get("usage") or {}
            # normalize Anthropic + OpenAI shapes
            self.usage = {
                "input_tokens": int(u.get("input_tokens") or u.get("prompt_tokens") or 0),
                "output_tokens": int(u.get("output_tokens") or u.get("completion_tokens") or 0),
            }


class LLMClient:
    def __init__(self, cfg: LLMConfig | None = None) -> None:
        self.cfg = cfg or load_llm_config()
        timeout = httpx.Timeout(connect=15.0, read=180.0, write=30.0, pool=15.0)
        # trust_env=False: ignore system proxy (e.g. Windows registry SOCKS) so the
        # provider URL is reached directly. Set HTTPS_PROXY in .env to opt back in.
        self._client = httpx.AsyncClient(timeout=timeout, trust_env=False)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, str]],
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> LLMReply:
        cfg = self.cfg
        if not cfg.api_key:
            raise RuntimeError(
                "LLM API key is not configured. Set AGUI_LLM_API_KEY (or a "
                "provider-specific env var like ANTHROPIC_AUTH_TOKEN)."
            )

        if cfg.protocol == "anthropic":
            return await self._call_anthropic(system, messages, max_tokens, temperature)
        if cfg.protocol == "openai":
            return await self._call_openai(system, messages, max_tokens, temperature)
        raise RuntimeError(f"Unsupported protocol {cfg.protocol!r}")

    async def _call_anthropic(
        self,
        system: str,
        messages: list[dict[str, str]],
        max_tokens: int | None,
        temperature: float | None,
    ) -> LLMReply:
        cfg = self.cfg
        url = f"{cfg.base_url}/v1/messages"
        payload = {
            "model": cfg.model,
            "system": system,
            "max_tokens": max_tokens or cfg.max_tokens,
            "temperature": temperature if temperature is not None else cfg.temperature,
            "messages": messages,
        }
        headers = {
            "content-type": "application/json",
            "x-api-key": cfg.api_key,
            "anthropic-version": "2023-06-01",
            "authorization": f"Bearer {cfg.api_key}",
        }
        r = await self._client.post(url, headers=headers, json=payload)
        r.raise_for_status()
        data = r.json()
        text_chunks: list[str] = []
        for block in data.get("content", []) or []:
            btype = block.get("type")
            if btype == "text":
                text_chunks.append(block.get("text", ""))
            elif btype == "thinking":
                # ignore reasoning, keep only visible text
                continue
        return LLMReply(text="".join(text_chunks).strip(), raw=data)

    async def _call_openai(
        self,
        system: str,
        messages: list[dict[str, str]],
        max_tokens: int | None,
        temperature: float | None,
    ) -> LLMReply:
        cfg = self.cfg
        url = f"{cfg.base_url}/chat/completions"
        all_msgs = [{"role": "system", "content": system}] + messages
        payload = {
            "model": cfg.model,
            "messages": all_msgs,
            "max_tokens": max_tokens or cfg.max_tokens,
            "temperature": temperature if temperature is not None else cfg.temperature,
        }
        headers = {
            "content-type": "application/json",
            "authorization": f"Bearer {cfg.api_key}",
        }
        r = await self._client.post(url, headers=headers, json=payload)
        r.raise_for_status()
        data = r.json()
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message", {}) or {}
        text = message.get("content") or ""
        return LLMReply(text=text.strip(), raw=data)

    # ------------------------------------------------------------------
    # Streaming — yields text chunks as the model emits them, then the
    # final LLMReply via the closure on `final`. Used by codegen to push
    # progressive HTML into the iframe while the LLM is still drawing.
    # ------------------------------------------------------------------

    async def complete_stream(
        self,
        *,
        system: str,
        messages: list[dict[str, str]],
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> AsyncIterator[str]:
        cfg = self.cfg
        if not cfg.api_key:
            raise RuntimeError("LLM API key is not configured.")
        if cfg.protocol == "anthropic":
            async for chunk in self._stream_anthropic(system, messages, max_tokens, temperature):
                yield chunk
            return
        if cfg.protocol == "openai":
            async for chunk in self._stream_openai(system, messages, max_tokens, temperature):
                yield chunk
            return
        raise RuntimeError(f"Unsupported protocol {cfg.protocol!r}")

    async def _stream_anthropic(
        self,
        system: str,
        messages: list[dict[str, str]],
        max_tokens: int | None,
        temperature: float | None,
    ) -> AsyncIterator[str]:
        cfg = self.cfg
        url = f"{cfg.base_url}/v1/messages"
        payload = {
            "model": cfg.model,
            "system": system,
            "max_tokens": max_tokens or cfg.max_tokens,
            "temperature": temperature if temperature is not None else cfg.temperature,
            "messages": messages,
            "stream": True,
        }
        headers = {
            "content-type": "application/json",
            "x-api-key": cfg.api_key,
            "anthropic-version": "2023-06-01",
            "authorization": f"Bearer {cfg.api_key}",
            "accept": "text/event-stream",
        }
        async with self._client.stream("POST", url, headers=headers, json=payload) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()
                if not data_str:
                    continue
                try:
                    evt = json.loads(data_str)
                except json.JSONDecodeError:
                    continue
                etype = evt.get("type")
                if etype == "content_block_delta":
                    delta = evt.get("delta") or {}
                    if delta.get("type") == "text_delta":
                        text = delta.get("text") or ""
                        if text:
                            yield text
                elif etype == "message_stop":
                    return

    async def _stream_openai(
        self,
        system: str,
        messages: list[dict[str, str]],
        max_tokens: int | None,
        temperature: float | None,
    ) -> AsyncIterator[str]:
        cfg = self.cfg
        url = f"{cfg.base_url}/chat/completions"
        all_msgs = [{"role": "system", "content": system}] + messages
        payload = {
            "model": cfg.model,
            "messages": all_msgs,
            "max_tokens": max_tokens or cfg.max_tokens,
            "temperature": temperature if temperature is not None else cfg.temperature,
            "stream": True,
        }
        headers = {
            "content-type": "application/json",
            "authorization": f"Bearer {cfg.api_key}",
            "accept": "text/event-stream",
        }
        async with self._client.stream("POST", url, headers=headers, json=payload) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()
                if data_str == "[DONE]":
                    return
                if not data_str:
                    continue
                try:
                    evt = json.loads(data_str)
                except json.JSONDecodeError:
                    continue
                choices = evt.get("choices") or []
                if not choices:
                    continue
                delta = (choices[0] or {}).get("delta") or {}
                text = delta.get("content")
                if text:
                    yield text


_JSON_FENCE = re.compile(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", re.DOTALL)
_HTML_FENCE = re.compile(r"```(?:html)?\s*(<!DOCTYPE html.*?</html>)\s*```", re.DOTALL | re.IGNORECASE)


def extract_json(text: str) -> Any:
    """Best-effort JSON extraction from a model reply."""
    if not text:
        raise ValueError("empty LLM reply")
    m = _JSON_FENCE.search(text)
    if m:
        return json.loads(m.group(1))
    stripped = text.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        return json.loads(stripped)
    # try to find first {...} or [...] span
    for opener, closer in (("{", "}"), ("[", "]")):
        i = text.find(opener)
        j = text.rfind(closer)
        if i != -1 and j != -1 and j > i:
            try:
                return json.loads(text[i : j + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError(f"could not parse JSON from reply: {text[:200]}...")


def extract_html(text: str) -> str:
    """Best-effort HTML document extraction from a model reply."""
    if not text:
        raise ValueError("empty LLM reply")
    m = _HTML_FENCE.search(text)
    if m:
        return m.group(1).strip()
    # If the model returned a raw doc without fences
    lower = text.lower()
    start = lower.find("<!doctype html")
    if start == -1:
        start = lower.find("<html")
    if start != -1:
        end = lower.rfind("</html>")
        if end != -1:
            return text[start : end + len("</html>")].strip()
    # Last resort: wrap whatever we got in a minimal scaffold
    return text.strip()
