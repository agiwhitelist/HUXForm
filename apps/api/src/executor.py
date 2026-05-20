"""Execution Broker + Permission Layer.

Every call from generated UI passes through here. We resolve the tool,
check policy, optionally wait for human approval, run it, and emit
appropriate events on the turn's stream.

Permission Layer rules:
  read           → execute without prompt
  network/write  → execute without prompt (audited)
  destructive    → require human approval (dry-run mode supported)
  filesystem     → require human approval
  secret         → require human approval
"""

from __future__ import annotations

import asyncio
import inspect
import time
from collections import defaultdict
from typing import Any

from .tasks import Turn
from .tools import Tool, ToolRegistry


class ApprovalDenied(RuntimeError):
    pass


class ToolNotFound(RuntimeError):
    pass


class Cancelled(RuntimeError):
    pass


_AUTO_APPROVE_RISKS = {"read", "write", "network"}


def _needs_approval(tool: Tool) -> bool:
    if tool.requires_approval:
        return True
    if tool.risk in _AUTO_APPROVE_RISKS:
        return False
    return True  # destructive / filesystem / secret


class Executor:
    def __init__(self, registry: ToolRegistry, approval_timeout: float = 300.0) -> None:
        self.registry = registry
        self.approval_timeout = approval_timeout
        # Per-tool call stats: name -> {count, total_ms, fail, last_ms, p_durations}
        # `p_durations` keeps a rolling window of the last 200 durations so we
        # can compute approximate p50/p95 without a real histogram.
        self._stats: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"count": 0, "total_ms": 0.0, "fail": 0, "last_ms": 0.0, "p_durations": []}
        )

    def stats(self) -> dict[str, Any]:
        """Aggregate per-tool latency + failure stats for the cost dashboard."""
        out = []
        grand_total = 0.0
        grand_count = 0
        for name, s in sorted(self._stats.items()):
            durations = sorted(s["p_durations"])
            n = len(durations)
            p50 = durations[n // 2] if n else 0.0
            p95 = durations[int(n * 0.95)] if n else 0.0
            avg = (s["total_ms"] / s["count"]) if s["count"] else 0.0
            grand_total += s["total_ms"]
            grand_count += s["count"]
            out.append({
                "tool": name,
                "count": s["count"],
                "fail": s["fail"],
                "total_ms": round(s["total_ms"], 1),
                "avg_ms": round(avg, 1),
                "p50_ms": round(p50, 1),
                "p95_ms": round(p95, 1),
                "last_ms": round(s["last_ms"], 1),
            })
        out.sort(key=lambda r: -r["total_ms"])
        return {
            "tools": out,
            "totals": {
                "calls": grand_count,
                "total_ms": round(grand_total, 1),
            },
        }

    def _record(self, name: str, duration_ms: float, ok: bool) -> None:
        s = self._stats[name]
        s["count"] += 1
        s["total_ms"] += duration_ms
        s["last_ms"] = duration_ms
        if not ok:
            s["fail"] += 1
        ring: list[float] = s["p_durations"]
        ring.append(duration_ms)
        if len(ring) > 200:
            del ring[0]

    async def call(self, turn: Turn, name: str, params: dict[str, Any]) -> Any:
        if turn.cancelled:
            raise Cancelled(turn.id)
        tool = self.registry.get(name)
        if tool is None:
            turn.emit({"type": "error", "message": f"unknown tool: {name}", "recoverable": True})
            raise ToolNotFound(name)

        dry_run = bool(params.pop("__dry_run", False)) if isinstance(params, dict) else False

        turn.emit({
            "type": "tool_called",
            "tool": name,
            "title": tool.title,
            "risk": tool.risk,
            "params_preview": _preview(params),
            "dry_run": dry_run,
        })

        if _needs_approval(tool) and not dry_run:
            approved = await self._await_approval(turn, tool, params)
            if not approved:
                turn.emit({"type": "tool_denied", "tool": name})
                raise ApprovalDenied(name)

        if turn.cancelled:
            raise Cancelled(turn.id)

        if dry_run:
            preview = {
                "tool": name,
                "params": params,
                "would_call": True,
                "risk": tool.risk,
            }
            turn.emit({"type": "tool_dry_run", "tool": name, "preview": _preview(preview)})
            return {"dry_run": True, "preview": preview}

        start = time.perf_counter()
        try:
            kwargs = dict(params or {})
            sig = inspect.signature(tool.handler)
            if "turn_ref" in sig.parameters:
                kwargs["turn_ref"] = turn
            result = await tool.handler(**kwargs)
        except Exception as exc:
            duration_ms = (time.perf_counter() - start) * 1000.0
            self._record(name, duration_ms, ok=False)
            turn.emit({"type": "tool_error", "tool": name, "message": str(exc), "duration_ms": round(duration_ms, 1)})
            raise

        duration_ms = (time.perf_counter() - start) * 1000.0
        self._record(name, duration_ms, ok=True)
        turn.emit({
            "type": "tool_result",
            "tool": name,
            "result_preview": _preview(result),
            "duration_ms": round(duration_ms, 1),
        })
        return result

    async def _await_approval(self, turn: Turn, tool: Tool, params: dict[str, Any]) -> bool:
        approval_id = f"appr_{len(turn._pending_approvals) + 1}_{tool.name}"
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[bool] = loop.create_future()
        turn._pending_approvals[approval_id] = fut
        prior_status = turn.status
        turn.status = "awaiting_approval"
        turn.emit({
            "type": "approval_required",
            "approval_id": approval_id,
            "tool": tool.name,
            "tool_title": tool.title,
            "risk": tool.risk,
            "params_preview": _preview(params),
            "description": tool.description,
        })
        try:
            return await asyncio.wait_for(fut, timeout=self.approval_timeout)
        except asyncio.TimeoutError:
            return False
        finally:
            turn._pending_approvals.pop(approval_id, None)
            if turn.status == "awaiting_approval":
                turn.status = prior_status

    def resolve_approval(self, turn: Turn, approval_id: str, approved: bool) -> bool:
        fut = turn._pending_approvals.get(approval_id)
        if fut is None or fut.done():
            return False
        fut.set_result(approved)
        return True


def _preview(value: Any, max_len: int = 500) -> Any:
    """Trim large values so events stay light."""
    if isinstance(value, str):
        return value if len(value) <= max_len else value[:max_len] + "…"
    if isinstance(value, list):
        if len(value) > 20:
            return [_preview(v, max_len // 4) for v in value[:20]] + [f"...(+{len(value) - 20} more)"]
        return [_preview(v, max_len // 4) for v in value]
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for i, (k, v) in enumerate(value.items()):
            if i >= 20:
                out["…"] = f"(+{len(value) - 20} more keys)"
                break
            out[k] = _preview(v, max_len // 4)
        return out
    return value
