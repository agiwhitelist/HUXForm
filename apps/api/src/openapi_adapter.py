"""OpenAPI adapter — expose any REST API as AGUI tools.

Given an OpenAPI 3.x spec (URL or file), walk every operation and register
it as a tool named "openapi.<alias>.<operationId>". At call time, build the
HTTP request from the operation's parameters/body, send it, return the
JSON response (or text).

Auth: per-spec bearer token / api-key, configured via env or registration.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

import httpx

from .tools import Tool, ToolRegistry


log = logging.getLogger("agui.openapi")

_SAFE_RE = re.compile(r"[^a-zA-Z0-9_]+")


def _slug(s: str) -> str:
    return _SAFE_RE.sub("_", s).strip("_") or "op"


@dataclass
class OpenAPIRegistration:
    alias: str
    spec_url: str
    base_url: str
    auth_header: tuple[str, str] | None = None  # (header_name, value)


class OpenAPIAdapter:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry
        self._client = httpx.AsyncClient(timeout=60.0, trust_env=False)
        self._regs: list[OpenAPIRegistration] = []

    async def aclose(self) -> None:
        await self._client.aclose()

    async def register_spec(self, reg: OpenAPIRegistration) -> int:
        if reg.spec_url.startswith(("http://", "https://")):
            r = await self._client.get(reg.spec_url)
            r.raise_for_status()
            spec = r.json() if "json" in r.headers.get("content-type", "") else json.loads(r.text)
        else:
            with open(reg.spec_url, "r", encoding="utf-8") as f:
                spec = json.load(f)

        base = reg.base_url
        if not base:
            servers = spec.get("servers") or []
            if servers:
                base = servers[0].get("url", "")
        if not base:
            base = reg.spec_url.rsplit("/", 1)[0]

        count = 0
        for path, methods in (spec.get("paths") or {}).items():
            if not isinstance(methods, dict):
                continue
            for method, op in methods.items():
                if method.lower() not in {"get", "post", "put", "patch", "delete"}:
                    continue
                if not isinstance(op, dict):
                    continue
                op_id = op.get("operationId") or _slug(f"{method}_{path}")
                tool_name = f"openapi.{reg.alias}.{_slug(op_id)}"
                summary = op.get("summary") or op.get("description") or f"{method.upper()} {path}"
                params_spec = op.get("parameters") or []
                request_body = op.get("requestBody") or {}

                risk = "network" if method.lower() in {"get"} else "write"
                if method.lower() == "delete":
                    risk = "destructive"

                async def handler(
                    _path=path, _method=method, _params=params_spec, _body=request_body,
                    _base=base, _auth=reg.auth_header, **kwargs,
                ):
                    return await self._call(_path, _method, _params, _body, _base, _auth, kwargs)

                self.registry.register(Tool(
                    name=tool_name,
                    title=op.get("summary") or tool_name,
                    description=summary,
                    risk=risk,
                    requires_approval=(risk in {"destructive"}),
                    params_schema=self._params_schema(params_spec, request_body),
                    handler=handler,
                    source=f"openapi:{reg.alias}",
                ))
                count += 1
        self._regs.append(reg)
        log.info("openapi:%s — %d operations registered", reg.alias, count)
        return count

    def _params_schema(self, params_spec: list[dict], request_body: dict) -> dict[str, Any]:
        schema: dict[str, Any] = {}
        for p in params_spec:
            name = p.get("name")
            if not name:
                continue
            optional = not p.get("required", False)
            schema[f"{name}{'?' if optional else ''}"] = p.get("in", "query") + ":" + (
                (p.get("schema") or {}).get("type") or "string"
            )
        if request_body:
            schema["body?"] = "object (request body)"
        return schema

    async def _call(
        self,
        path: str,
        method: str,
        params_spec: list[dict],
        request_body: dict,
        base: str,
        auth: tuple[str, str] | None,
        params: dict[str, Any],
    ) -> Any:
        url_path = path
        query: dict[str, Any] = {}
        headers: dict[str, str] = {}
        for p in params_spec:
            name = p.get("name")
            if name is None or name not in params:
                continue
            value = params.get(name)
            loc = p.get("in", "query")
            if loc == "path":
                url_path = url_path.replace(f"{{{name}}}", str(value))
            elif loc == "header":
                headers[name] = str(value)
            elif loc == "query":
                query[name] = value
        body = params.get("body")
        url = urljoin(base.rstrip("/") + "/", url_path.lstrip("/"))
        if auth:
            headers[auth[0]] = auth[1]
        r = await self._client.request(
            method.upper(), url, params=query or None, json=body, headers=headers,
        )
        ct = r.headers.get("content-type", "")
        result: Any
        try:
            result = r.json() if "json" in ct else r.text
        except Exception:
            result = r.text
        return {"status": r.status_code, "body": result}
