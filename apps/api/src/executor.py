"""Execution Broker + Permission Layer.

Every call from generated UI lands here. We resolve the tool, check the
permission policy, optionally suspend for human approval, run the
handler, and emit the appropriate events on the task's stream.
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any

from .tasks import Task
from .tools import Tool, ToolRegistry


class ApprovalDenied(RuntimeError):
    pass


class ToolNotFound(RuntimeError):
    pass


class Executor:
    def __init__(self, registry: ToolRegistry, approval_timeout: float = 300.0) -> None:
        self.registry = registry
        self.approval_timeout = approval_timeout

    async def call(self, task: Task, name: str, params: dict[str, Any]) -> Any:
        tool = self.registry.get(name)
        if tool is None:
            task.emit({"type": "error", "message": f"unknown tool: {name}", "recoverable": True})
            raise ToolNotFound(name)

        task.emit({
            "type": "tool_called",
            "tool": name,
            "risk": tool.risk,
            "params_preview": _preview(params),
        })

        if tool.requires_approval or tool.risk in ("destructive",):
            approved = await self._await_approval(task, tool, params)
            if not approved:
                task.emit({"type": "tool_denied", "tool": name})
                raise ApprovalDenied(name)

        try:
            kwargs = dict(params or {})
            # Inject task reference for tools that need it
            sig = inspect.signature(tool.handler)
            if "task_ref" in sig.parameters:
                kwargs["task_ref"] = task
            result = await tool.handler(**kwargs)
        except Exception as exc:  # surface to the UI cleanly
            task.emit({
                "type": "tool_error",
                "tool": name,
                "message": str(exc),
            })
            raise

        task.emit({
            "type": "tool_result",
            "tool": name,
            "result_preview": _preview(result),
        })
        return result

    async def _await_approval(self, task: Task, tool: Tool, params: dict[str, Any]) -> bool:
        approval_id = f"appr_{len(task._pending_approvals) + 1}_{tool.name}"
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[bool] = loop.create_future()
        task._pending_approvals[approval_id] = fut
        task.status = "awaiting_approval"
        task.emit({
            "type": "approval_required",
            "approval_id": approval_id,
            "tool": tool.name,
            "tool_title": tool.title,
            "risk": tool.risk,
            "params_preview": _preview(params),
        })
        try:
            return await asyncio.wait_for(fut, timeout=self.approval_timeout)
        except asyncio.TimeoutError:
            return False
        finally:
            task._pending_approvals.pop(approval_id, None)
            task.status = "running"

    def resolve_approval(self, task: Task, approval_id: str, approved: bool) -> bool:
        fut = task._pending_approvals.get(approval_id)
        if fut is None or fut.done():
            return False
        fut.set_result(approved)
        return True


def _preview(value: Any, max_len: int = 500) -> Any:
    """Trim large values so event streams stay light."""
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
