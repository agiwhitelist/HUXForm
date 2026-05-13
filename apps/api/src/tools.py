"""Built-in tool registry + execution broker.

Tools are the only way generated UI code is allowed to touch the outside
world. Each tool declares its name, description, parameter schema, and
risk class. The Permission Layer (see executor.py) decides whether a call
goes through immediately, needs approval, or is dry-run only.

This MVP ships a small, useful set of tools. Adding new tools is just a
matter of registering another @tool function — Tool Discovery / MCP /
CLI adapters plug in here later.
"""

from __future__ import annotations

import csv
import io
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from .llm import LLMClient, extract_json


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


@dataclass
class ToolRegistry:
    tools: dict[str, Tool] = field(default_factory=dict)

    def register(self, tool: Tool) -> None:
        self.tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self.tools.get(name)

    def describe(self) -> str:
        lines: list[str] = []
        for t in self.tools.values():
            lines.append(
                f"- {t.name} ({t.risk}{', approval' if t.requires_approval else ''}): {t.description}"
            )
        return "\n".join(lines)

    def bridge_schema(self) -> list[dict[str, Any]]:
        return [
            {
                "name": t.name,
                "title": t.title,
                "description": t.description,
                "risk": t.risk,
                "requires_approval": t.requires_approval,
                "params": t.params_schema,
            }
            for t in self.tools.values()
        ]


_REGISTRY = ToolRegistry()


def get_registry() -> ToolRegistry:
    return _REGISTRY


def describe_tools() -> str:
    return _REGISTRY.describe()


# ---------------------------------------------------------------------------
# Built-in tool implementations
# ---------------------------------------------------------------------------


async def _llm_ask(*, llm: LLMClient, prompt: str, system: str | None = None) -> dict[str, Any]:
    reply = await llm.complete(
        system=system or "You are a careful assistant inside AGUI. Be concise and concrete.",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.5,
    )
    return {"text": reply.text}


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
    return {"value": extract_json(reply.text)}


async def _web_search(*, llm: LLMClient, query: str, limit: int = 5) -> dict[str, Any]:
    """Stubbed web search.

    For the MVP we don't ship a real search backend; we ask the model to
    *invent* plausible candidates so generated UIs have something to draw.
    Wire this to a real search adapter (Tavily, Brave, SerpAPI) when ready.
    """
    sys = (
        "You simulate a web search result list. Return JSON: "
        '{"results": [{"title": str, "url": str, "snippet": str, "score": 0..1}]}'
        f". At most {limit} results. Use realistic-looking but clearly illustrative data."
    )
    reply = await llm.complete(
        system=sys,
        messages=[{"role": "user", "content": f"Query: {query}"}],
        temperature=0.4,
    )
    try:
        data = extract_json(reply.text)
    except ValueError:
        data = {"results": []}
    return data


_NUM_RE = re.compile(r"^-?\d+(?:\.\d+)?$")


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
    # infer column types
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
            dup_groups.append(
                {
                    "key": dict(zip(keys, key)),
                    "indices": indices,
                    "rows": [rows[i] for i in indices],
                    "count": len(indices),
                }
            )
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
            nums = []
            for v in non_empty:
                try:
                    nums.append(float(v))
                except (TypeError, ValueError):
                    pass
            if nums:
                col_summary.update(
                    {
                        "min": min(nums),
                        "max": max(nums),
                        "mean": sum(nums) / len(nums),
                    }
                )
        else:
            top = Counter(map(str, non_empty)).most_common(5)
            col_summary["top"] = [{"value": v, "count": c} for v, c in top]
        summary[col] = col_summary
    return {"summary": summary, "row_count": len(rows)}


async def _task_set_state(*, task_ref: Any, patch: dict[str, Any]) -> dict[str, Any]:
    task_ref.state.update(patch)
    task_ref.emit({"type": "state_patch", "patch": patch})
    return {"ok": True, "state": dict(task_ref.state)}


async def _task_final_result(*, task_ref: Any, result: Any) -> dict[str, Any]:
    task_ref.final_result = result
    task_ref.status = "done"
    task_ref.emit({"type": "final_result", "result": result})
    return {"ok": True}


async def _task_log(*, task_ref: Any, level: str, message: str) -> dict[str, Any]:
    task_ref.emit({"type": "log", "level": level, "message": message})
    return {"ok": True}


def register_builtin_tools(llm: LLMClient) -> ToolRegistry:
    """Populate the global registry. Idempotent."""
    _REGISTRY.tools.clear()

    _REGISTRY.register(Tool(
        name="llm.ask",
        title="Ask the underlying LLM",
        description="Send a free-form prompt to AGUI's underlying LLM and get text back. Use for short reasoning, summaries, copywriting.",
        risk="read",
        requires_approval=False,
        params_schema={"prompt": "string", "system?": "string"},
        handler=lambda **kw: _llm_ask(llm=llm, **kw),
    ))

    _REGISTRY.register(Tool(
        name="llm.structured",
        title="Ask the LLM for structured JSON",
        description="Generate a JSON value matching a schema hint. Use for plans, comparisons, lists of cards, scoring tables.",
        risk="read",
        requires_approval=False,
        params_schema={"prompt": "string", "schema_hint": "string"},
        handler=lambda **kw: _llm_structured(llm=llm, **kw),
    ))

    _REGISTRY.register(Tool(
        name="web.search",
        title="Web search",
        description="Search the public web. MVP: simulated results — wire to a real search backend in production.",
        risk="network",
        requires_approval=False,
        params_schema={"query": "string", "limit?": "integer"},
        handler=lambda **kw: _web_search(llm=llm, **kw),
    ))

    _REGISTRY.register(Tool(
        name="data.parse_csv",
        title="Parse CSV text",
        description="Parse CSV text into columns + typed rows. Sniffs delimiter automatically.",
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
        description="Per-column stats: non-empty, distinct, top values, min/max/mean for numeric columns.",
        risk="read",
        requires_approval=False,
        params_schema={"rows": "array<object>", "column_types?": "object"},
        handler=_csv_summarize,
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
        params_schema={"level": "string", "message": "string"},
        handler=_task_log,
    ))

    return _REGISTRY
