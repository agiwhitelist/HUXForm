"""Minimal MCP (Model Context Protocol) client for stdio servers.

We don't depend on an SDK — MCP is plain JSON-RPC over stdin/stdout with a
handful of methods. This client:

  * spawns each configured server as a subprocess,
  * performs `initialize` + `tools/list`,
  * registers every discovered tool into the AGUI ToolRegistry under the
    name "mcp.<server_alias>.<tool_name>",
  * routes calls back via `tools/call`.

Config file (default path: .agui/mcp.json):

    {
      "servers": [
        { "alias": "fs",   "command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"] },
        { "alias": "git",  "command": "uvx", "args": ["mcp-server-git", "--repository", "."] }
      ]
    }
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .tools import Tool, ToolRegistry


log = logging.getLogger("agui.mcp")


@dataclass
class MCPServerConfig:
    alias: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)


@dataclass
class _PendingRequest:
    future: asyncio.Future
    method: str


class MCPServer:
    """Single subprocess MCP server connection."""

    def __init__(self, cfg: MCPServerConfig) -> None:
        self.cfg = cfg
        self.proc: asyncio.subprocess.Process | None = None
        self._next_id = 1
        self._pending: dict[int, _PendingRequest] = {}
        self._reader_task: asyncio.Task | None = None
        self._stopped = False

    async def start(self) -> dict[str, Any]:
        env = {**os.environ, **(self.cfg.env or {})}
        self.proc = await asyncio.create_subprocess_exec(
            self.cfg.command, *self.cfg.args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        self._reader_task = asyncio.create_task(self._read_loop())
        result = await self.request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "agui", "version": "0.2.0"},
        }, timeout=20.0)
        await self.notify("notifications/initialized", {})
        return result

    async def stop(self) -> None:
        self._stopped = True
        if self.proc and self.proc.returncode is None:
            try:
                self.proc.terminate()
                await asyncio.wait_for(self.proc.wait(), timeout=3.0)
            except (asyncio.TimeoutError, ProcessLookupError):
                try:
                    self.proc.kill()
                except ProcessLookupError:
                    pass

    async def request(self, method: str, params: dict[str, Any], *, timeout: float = 60.0) -> Any:
        if not self.proc or self.proc.stdin is None:
            raise RuntimeError("MCP server not started")
        rid = self._next_id
        self._next_id += 1
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        self._pending[rid] = _PendingRequest(future=fut, method=method)
        msg = json.dumps({"jsonrpc": "2.0", "id": rid, "method": method, "params": params}) + "\n"
        self.proc.stdin.write(msg.encode("utf-8"))
        await self.proc.stdin.drain()
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        finally:
            self._pending.pop(rid, None)

    async def notify(self, method: str, params: dict[str, Any]) -> None:
        if not self.proc or self.proc.stdin is None:
            return
        msg = json.dumps({"jsonrpc": "2.0", "method": method, "params": params}) + "\n"
        self.proc.stdin.write(msg.encode("utf-8"))
        await self.proc.stdin.drain()

    async def list_tools(self) -> list[dict[str, Any]]:
        res = await self.request("tools/list", {})
        return list((res or {}).get("tools") or [])

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        return await self.request("tools/call", {"name": name, "arguments": arguments or {}})

    async def _read_loop(self) -> None:
        assert self.proc and self.proc.stdout
        buf = b""
        while not self._stopped:
            chunk = await self.proc.stdout.readline()
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line.decode("utf-8"))
                except json.JSONDecodeError:
                    log.debug("MCP %s: non-JSON line ignored: %r", self.cfg.alias, line[:120])
                    continue
                self._dispatch(msg)
        for p in list(self._pending.values()):
            if not p.future.done():
                p.future.set_exception(RuntimeError("MCP server closed"))

    def _dispatch(self, msg: dict[str, Any]) -> None:
        rid = msg.get("id")
        if rid is not None and rid in self._pending:
            pending = self._pending[rid]
            if "error" in msg:
                err = msg["error"]
                pending.future.set_exception(
                    RuntimeError(f"MCP {pending.method}: {err.get('message', err)}")
                )
            else:
                pending.future.set_result(msg.get("result"))


class MCPManager:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry
        self.servers: dict[str, MCPServer] = {}

    async def start_from_config(self, config_path: str | Path) -> int:
        cfg_path = Path(config_path)
        if not cfg_path.exists():
            log.info("No MCP config at %s — skipping", cfg_path)
            return 0
        try:
            data = json.loads(cfg_path.read_text())
        except json.JSONDecodeError as exc:
            log.error("MCP config %s is not valid JSON: %s", cfg_path, exc)
            return 0
        configs = [
            MCPServerConfig(
                alias=s["alias"],
                command=s["command"],
                args=list(s.get("args") or []),
                env=dict(s.get("env") or {}),
            )
            for s in (data.get("servers") or [])
        ]
        return await self.start_servers(configs)

    async def start_servers(self, configs: list[MCPServerConfig]) -> int:
        total = 0
        for cfg in configs:
            try:
                server = MCPServer(cfg)
                await server.start()
                tools = await server.list_tools()
                self.servers[cfg.alias] = server
                for t in tools:
                    self._register_tool(cfg.alias, server, t)
                total += len(tools)
                log.info("MCP %s: %d tools registered", cfg.alias, len(tools))
            except Exception as exc:
                log.exception("MCP %s failed to start: %s", cfg.alias, exc)
        return total

    def _register_tool(self, alias: str, server: MCPServer, spec: dict[str, Any]) -> None:
        name = f"mcp.{alias}.{spec.get('name')}"
        title = spec.get("title") or spec.get("name") or name
        description = spec.get("description") or f"MCP tool from {alias}"
        schema = spec.get("inputSchema") or {}

        async def handler(**params):
            res = await server.call_tool(spec["name"], params)
            return res

        self.registry.register(Tool(
            name=name,
            title=title,
            description=description,
            risk="network",
            requires_approval=False,
            params_schema=schema,
            handler=handler,
            source=f"mcp:{alias}",
        ))

    async def stop_all(self) -> None:
        for s in self.servers.values():
            await s.stop()
        self.servers.clear()
