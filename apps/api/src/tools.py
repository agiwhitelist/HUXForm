"""Built-in tool registry + handlers.

This module exposes a process-wide ToolRegistry. The base set is registered
by register_builtin_tools(); discovery adapters (MCP, OpenAPI, CLI) add
more at startup or on user request.
"""

from __future__ import annotations

import asyncio
import base64
import csv
import io
import os
import re
import shutil
import subprocess
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from .llm import LLMClient, extract_json
from .web_search import web_fetch, web_search


Risk = str  # "read" | "write" | "destructive" | "network" | "filesystem" | "secret"


@dataclass
class Tool:
    name: str
    title: str
    description: str
    risk: Risk
    params_schema: dict[str, Any]
    requires_approval: bool
    handler: Callable[..., Awaitable[Any]]
    source: str = "builtin"  # builtin | mcp | openapi | cli | discovered
    examples: list[str] = field(default_factory=list)
    # ── Full Capability Registry fields (from idea.md) ──────────────────
    install: dict[str, Any] | None = None           # { type, command, args }
    trust_score: float | None = None                # 0..1, set by Discovery
    permissions: list[str] = field(default_factory=list)
    title_id: str | None = None                     # human-friendly slug


@dataclass
class ToolRegistry:
    tools: dict[str, Tool] = field(default_factory=dict)

    def register(self, tool: Tool) -> None:
        self.tools[tool.name] = tool

    def unregister(self, name: str) -> None:
        self.tools.pop(name, None)

    def get(self, name: str) -> Tool | None:
        return self.tools.get(name)

    def describe(self) -> str:
        lines: list[str] = []
        for t in self.tools.values():
            extra = ", approval" if t.requires_approval else ""
            lines.append(f"- {t.name} [{t.source}] ({t.risk}{extra}): {t.description}")
        return "\n".join(lines)

    def bridge_schema(self) -> list[dict[str, Any]]:
        return [
            {
                "name": t.name,
                "title": t.title,
                "description": t.description,
                "risk": t.risk,
                "requires_approval": t.requires_approval,
                "source": t.source,
                "params": t.params_schema,
                "examples": t.examples,
                "install": t.install,
                "trust_score": t.trust_score,
                "permissions": t.permissions,
            }
            for t in self.tools.values()
        ]


_REGISTRY = ToolRegistry()


def get_registry() -> ToolRegistry:
    return _REGISTRY


def describe_tools() -> str:
    return _REGISTRY.describe()


# ---------------------------------------------------------------------------
# Built-in handlers
# ---------------------------------------------------------------------------


async def _llm_ask(*, llm: LLMClient, prompt: str, system: str | None = None) -> dict[str, Any]:
    reply = await llm.complete(
        system=system or "You are a careful assistant inside AGUI. Be concise and concrete.",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.5,
    )
    return {"text": reply.text, "usage": reply.usage}


async def _llm_structured(*, llm: LLMClient, prompt: str, schema_hint: str) -> dict[str, Any]:
    sys = (
        "You generate ONLY a single JSON value matching the user's described schema. "
        "No prose, no markdown, no commentary."
    )
    user = f"Schema hint:\n{schema_hint}\n\nTask:\n{prompt}\n\nReturn JSON now."
    reply = await llm.complete(
        system=sys,
        messages=[{"role": "user", "content": user}],
        temperature=0.2,
    )
    return {"value": extract_json(reply.text), "usage": reply.usage}


async def _web_search(*, query: str, limit: int = 6) -> dict[str, Any]:
    return await web_search(query, limit=int(limit))


async def _web_fetch(*, url: str, max_bytes: int = 800_000, extract_links: bool = False) -> dict[str, Any]:
    return await web_fetch(url, max_bytes=int(max_bytes), extract_links=bool(extract_links))


_NUM_RE = re.compile(r"^-?\d+(?:[.,]\d+)?$")


async def _csv_parse(*, text: str, delimiter: str | None = None) -> dict[str, Any]:
    if not text:
        return {"columns": [], "rows": [], "row_count": 0}
    sample = text[:4096]
    if delimiter is None:
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
            delimiter = dialect.delimiter
        except csv.Error:
            delimiter = ","
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows = list(reader)
    if not rows:
        return {"columns": [], "rows": [], "row_count": 0}
    columns = rows[0]
    data_rows = [dict(zip(columns, r)) for r in rows[1:] if any(c.strip() for c in r)]
    col_types: dict[str, str] = {}
    for col in columns:
        sample_vals = [r.get(col, "") for r in data_rows[:200] if r.get(col, "").strip()]
        if sample_vals and all(_NUM_RE.match(v.strip()) for v in sample_vals):
            col_types[col] = "number"
        else:
            col_types[col] = "string"
    return {
        "columns": columns,
        "column_types": col_types,
        "rows": data_rows,
        "row_count": len(data_rows),
        "delimiter": delimiter,
    }


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


async def _csv_find_duplicates(
    *,
    rows: list[dict[str, Any]],
    keys: list[str] | None = None,
) -> dict[str, Any]:
    if not rows:
        return {"groups": [], "duplicate_rows": 0, "unique_rows": 0}
    if not keys:
        keys = list(rows[0].keys())
    groups: dict[tuple, list[int]] = defaultdict(list)
    for idx, row in enumerate(rows):
        key = tuple(_norm(str(row.get(k, ""))) for k in keys)
        groups[key].append(idx)
    dup_groups = []
    duplicate_rows = 0
    for key, indices in groups.items():
        if len(indices) > 1:
            duplicate_rows += len(indices)
            dup_groups.append({
                "key": dict(zip(keys, key)),
                "indices": indices,
                "rows": [rows[i] for i in indices],
                "count": len(indices),
            })
    dup_groups.sort(key=lambda g: g["count"], reverse=True)
    return {
        "groups": dup_groups,
        "group_count": len(dup_groups),
        "duplicate_rows": duplicate_rows,
        "unique_rows": len(rows) - duplicate_rows + len(dup_groups),
        "keys": keys,
    }


async def _csv_summarize(*, rows: list[dict[str, Any]], column_types: dict[str, str] | None = None) -> dict[str, Any]:
    if not rows:
        return {"summary": {}}
    column_types = column_types or {}
    summary: dict[str, Any] = {}
    cols = list(rows[0].keys())
    for col in cols:
        values = [r.get(col, "") for r in rows]
        non_empty = [v for v in values if str(v).strip() != ""]
        col_summary: dict[str, Any] = {
            "non_empty": len(non_empty),
            "empty": len(values) - len(non_empty),
            "distinct": len(set(map(str, non_empty))),
        }
        if column_types.get(col) == "number":
            nums: list[float] = []
            for v in non_empty:
                try:
                    nums.append(float(str(v).replace(",", ".")))
                except (TypeError, ValueError):
                    pass
            if nums:
                col_summary.update({
                    "min": min(nums),
                    "max": max(nums),
                    "mean": sum(nums) / len(nums),
                })
        else:
            top = Counter(map(str, non_empty)).most_common(5)
            col_summary["top"] = [{"value": v, "count": c} for v, c in top]
        summary[col] = col_summary
    return {"summary": summary, "row_count": len(rows)}


async def _files_read(*, file_id: str, turn_ref: Any) -> dict[str, Any]:
    from .runtime import registry as get_runtime_registry  # local import to avoid cycle
    reg = get_runtime_registry()
    rec = reg.get_file(file_id)
    if rec is None or file_id not in (turn_ref.file_ids or []):
        raise ValueError(f"file not found or not attached to this turn: {file_id}")
    with open(rec.path, "rb") as f:
        raw = f.read()
    # Try utf-8 text first
    try:
        text = raw.decode("utf-8")
        return {"name": rec.name, "mime": rec.mime, "size": rec.size, "text": text}
    except UnicodeDecodeError:
        return {
            "name": rec.name,
            "mime": rec.mime,
            "size": rec.size,
            "base64": base64.b64encode(raw).decode("ascii"),
        }


async def _task_set_state(*, turn_ref: Any, patch: dict[str, Any]) -> dict[str, Any]:
    turn_ref.state.update(patch)
    turn_ref.emit({"type": "state_patch", "patch": patch})
    return {"ok": True, "state": dict(turn_ref.state)}


async def _task_final_result(*, turn_ref: Any, result: Any) -> dict[str, Any]:
    turn_ref.final_result = result
    turn_ref.status = "done"
    turn_ref.emit({"type": "final_result", "result": result})
    return {"ok": True}


async def _task_log(*, turn_ref: Any, level: str = "info", message: str = "") -> dict[str, Any]:
    turn_ref.emit({"type": "log", "level": level, "message": message})
    return {"ok": True}


# ---------------------------------------------------------------------------
# CLI exec (sandboxed-ish; off by default unless AGUI_ENABLE_CLI=1)
# ---------------------------------------------------------------------------

_CLI_ALLOW = set(os.environ.get("AGUI_CLI_ALLOWLIST", "").split(":")) if os.environ.get("AGUI_CLI_ALLOWLIST") else set()


async def _cli_exec(*, command: str, args: list[str] | None = None, timeout: int = 30) -> dict[str, Any]:
    if not os.environ.get("AGUI_ENABLE_CLI"):
        raise RuntimeError("cli.exec is disabled (set AGUI_ENABLE_CLI=1 to enable)")
    if _CLI_ALLOW and command not in _CLI_ALLOW:
        raise RuntimeError(f"command not in AGUI_CLI_ALLOWLIST: {command}")
    binpath = shutil.which(command)
    if not binpath:
        raise FileNotFoundError(command)
    proc = await asyncio.create_subprocess_exec(
        binpath, *(args or []),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise
    return {
        "exit": proc.returncode,
        "stdout": out.decode("utf-8", errors="replace"),
        "stderr": err.decode("utf-8", errors="replace"),
    }


# ---------------------------------------------------------------------------
# CLI discovery (introspect PATH at startup)
# ---------------------------------------------------------------------------


_INTERESTING_BINS = [
    "git", "gh", "curl", "jq", "python", "node", "npm", "pip", "uv", "ls", "rg",
    "find", "head", "tail", "wc", "tr", "sort", "uniq", "cat", "echo", "date",
    "make", "docker", "kubectl", "psql", "redis-cli", "ffmpeg",
]


def discover_cli_tools(registry: ToolRegistry) -> int:
    """Register cli.<name> tools for binaries we know about. Off unless AGUI_ENABLE_CLI=1."""
    if not os.environ.get("AGUI_ENABLE_CLI"):
        return 0
    n = 0
    for name in _INTERESTING_BINS:
        path = shutil.which(name)
        if not path:
            continue
        # Best-effort description from first line of --help
        desc = ""
        try:
            r = subprocess.run([path, "--help"], capture_output=True, text=True, timeout=2)
            head = (r.stdout or r.stderr or "").strip().splitlines()[:1]
            desc = head[0].strip() if head else ""
        except Exception:
            desc = ""
        description = f"Run `{name}` CLI. {desc}".strip()
        risk: Risk = "destructive" if name in ("docker", "kubectl", "rm", "git") else "filesystem"
        registry.register(Tool(
            name=f"cli.{name}",
            title=f"Run {name}",
            description=description,
            risk=risk,
            requires_approval=True,
            params_schema={"args?": "array<string>", "timeout?": "integer"},
            handler=lambda command=name, **kw: _cli_exec(command=command, **kw),
            source="cli",
        ))
        n += 1
    return n


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------


def register_builtin_tools(
    llm: LLMClient,
    *,
    mcp_manager: Any = None,
    capability_registry: Any = None,
) -> ToolRegistry:
    _REGISTRY.tools.clear()

    _REGISTRY.register(Tool(
        name="llm.ask",
        title="Ask the underlying LLM",
        description="Send a free-form prompt to HUXForm's LLM. Use for short reasoning, summaries, copywriting.",
        risk="read",
        requires_approval=False,
        params_schema={"prompt": "string", "system?": "string"},
        handler=lambda **kw: _llm_ask(llm=llm, **kw),
    ))

    _REGISTRY.register(Tool(
        name="llm.structured",
        title="Ask the LLM for structured JSON",
        description="Generate a JSON value matching a schema hint. Use for plans, comparisons, scoring tables.",
        risk="read",
        requires_approval=False,
        params_schema={"prompt": "string", "schema_hint": "string"},
        handler=lambda **kw: _llm_structured(llm=llm, **kw),
    ))

    # web.search picks the best provider available at call time. DDG is the
    # zero-config floor, Tavily/Brave/Serper take over if a key is set.
    has_premium = any(
        os.environ.get(k) for k in ("TAVILY_API_KEY", "BRAVE_API_KEY", "SERPER_API_KEY")
    )
    _REGISTRY.register(Tool(
        name="web.search",
        title="Web search",
        description=(
            "Search the public web. Returns real results (DuckDuckGo by default; "
            "Tavily/Brave/Serper used automatically if their API key is set)."
            if not has_premium else
            "Search the public web (provider auto-selected from configured keys: "
            "Tavily > Brave > Serper > DuckDuckGo)."
        ),
        risk="network",
        requires_approval=False,
        params_schema={"query": "string", "limit?": "integer"},
        handler=_web_search,
        examples=[
            "current weather in New York City",
            "best MCP servers for filesystem access",
        ],
    ))

    _REGISTRY.register(Tool(
        name="web.fetch",
        title="Fetch a URL",
        description=(
            "Download a URL and return readable text. Strips HTML, extracts "
            "<title> / meta description, can return outgoing links. JSON URLs "
            "are parsed automatically."
        ),
        risk="network",
        requires_approval=False,
        params_schema={"url": "string", "max_bytes?": "integer", "extract_links?": "boolean"},
        handler=_web_fetch,
        examples=["https://example.com"],
    ))

    _REGISTRY.register(Tool(
        name="data.parse_csv",
        title="Parse CSV text",
        description="Parse CSV text into typed columns + rows. Sniffs delimiter automatically.",
        risk="read",
        requires_approval=False,
        params_schema={"text": "string", "delimiter?": "string"},
        handler=_csv_parse,
    ))

    _REGISTRY.register(Tool(
        name="data.find_duplicates",
        title="Find duplicate rows",
        description="Group rows by chosen key columns and return duplicate groups.",
        risk="read",
        requires_approval=False,
        params_schema={"rows": "array<object>", "keys?": "array<string>"},
        handler=_csv_find_duplicates,
    ))

    _REGISTRY.register(Tool(
        name="data.summarize",
        title="Summarize tabular data",
        description="Per-column stats: non-empty, distinct, top values, min/max/mean.",
        risk="read",
        requires_approval=False,
        params_schema={"rows": "array<object>", "column_types?": "object"},
        handler=_csv_summarize,
    ))

    _REGISTRY.register(Tool(
        name="files.read",
        title="Read an attached file",
        description="Read a file the user attached to this turn. Returns text if UTF-8, otherwise base64.",
        risk="read",
        requires_approval=False,
        params_schema={"file_id": "string"},
        handler=_files_read,
    ))

    _REGISTRY.register(Tool(
        name="task.set_state",
        title="Patch task state",
        description="Merge a patch into the persistent task state and emit a state_patch event.",
        risk="write",
        requires_approval=False,
        params_schema={"patch": "object"},
        handler=_task_set_state,
    ))

    _REGISTRY.register(Tool(
        name="task.final_result",
        title="Report the final result",
        description="Call once when the task is complete. Emits final_result and marks the task done.",
        risk="write",
        requires_approval=False,
        params_schema={"result": "any"},
        handler=_task_final_result,
    ))

    _REGISTRY.register(Tool(
        name="task.log",
        title="Emit a log event",
        description="Push a log event into the task event stream. Level: info | warn | error.",
        risk="write",
        requires_approval=False,
        params_schema={"level?": "string", "message": "string"},
        handler=_task_log,
    ))

    discover_cli_tools(_REGISTRY)

    # Tool Discovery v0: tools.discover / tools.install / tools.uninstall.
    # Only registered when the lifespan passed in a manager + capability registry.
    if mcp_manager is not None and capability_registry is not None:
        from .discovery import discover_tools, install_mcp_server, uninstall_mcp_server

        async def _tools_discover(
            *,
            query: str,
            limit_per_source: int = 6,
            audit_top: int = 0,
        ) -> dict[str, Any]:
            return await discover_tools(
                query,
                limit_per_source=int(limit_per_source),
                audit_top=int(audit_top),
                llm=llm if int(audit_top) > 0 else None,
            )

        async def _tools_install(
            *,
            alias: str,
            command: str,
            args: list[str] | None = None,
            env: dict[str, str] | None = None,
            trust_score: float | None = None,
            install_type: str = "npx",
            source_url: str | None = None,
            description: str | None = None,
        ) -> dict[str, Any]:
            return await install_mcp_server(
                manager=mcp_manager,
                registry=capability_registry,
                alias=alias,
                command=command,
                args=list(args or []),
                env=dict(env or {}),
                trust_score=trust_score,
                install_type=install_type,
                source_url=source_url,
                description=description,
            )

        async def _tools_uninstall(*, alias: str) -> dict[str, Any]:
            return await uninstall_mcp_server(
                manager=mcp_manager,
                registry=capability_registry,
                alias=alias,
            )

        _REGISTRY.register(Tool(
            name="tools.discover",
            title="Discover new tools",
            description=(
                "Search the public MCP ecosystem (GitHub topic:mcp-server + npm) "
                "for tools that match the query. Returns candidates with a trust "
                "score and suggested install command. Calling this never installs "
                "anything — use tools.install to spawn a candidate. Pass "
                "audit_top=3 to LLM-audit the top three READMEs for permissions "
                "and trustworthiness (slower but a much better trust signal)."
            ),
            risk="network",
            requires_approval=False,
            params_schema={
                "query": "string",
                "limit_per_source?": "integer",
                "audit_top?": "integer",
            },
            handler=_tools_discover,
            examples=[
                "filesystem",
                "slack",
                "github issue tracker",
            ],
        ))

        _REGISTRY.register(Tool(
            name="tools.install",
            title="Install an MCP server",
            description=(
                "Spawn an MCP server as a child process and register every tool it "
                "advertises. Requires explicit human approval for each install. "
                "On success the new tools appear as mcp.<alias>.<tool_name>."
            ),
            risk="destructive",  # spawning a subprocess = destructive class → approval each time
            requires_approval=True,
            params_schema={
                "alias": "string",
                "command": "string",
                "args?": "array<string>",
                "env?": "object",
                "trust_score?": "number",
                "install_type?": "string",
                "source_url?": "string",
                "description?": "string",
            },
            handler=_tools_install,
        ))

        _REGISTRY.register(Tool(
            name="tools.uninstall",
            title="Uninstall an MCP server",
            description=(
                "Stop a running MCP server, unregister every tool it advertised "
                "(mcp.<alias>.*), and drop the install record from the persistent "
                "capability registry. Requires explicit human approval."
            ),
            risk="destructive",
            requires_approval=True,
            params_schema={"alias": "string"},
            handler=_tools_uninstall,
        ))

    return _REGISTRY
