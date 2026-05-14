"""Server-side Researcher loop.

This is the missing agentic step between the Director (decides WHAT and HOW)
and the UI Generator (renders). Without it, every generated UI would either
hallucinate data into HTML or hope the iframe's bundled JS thinks to make
the right tool call at runtime — both unreliable.

The Researcher works like a tiny ReAct loop:

  1. Look at the goal, the plan, the visual brief's metaphor, the available
     auto-approved tools (read / network / write — never destructive), and
     the prior research steps.
  2. Decide: call a tool to gather data, or stop because we have enough.
  3. Execute the call through the same Executor the iframe bridge uses —
     so every research step is audited and emits the normal `tool_called` /
     `tool_result` events the UI shell already streams.
  4. Cap results to a reasonable size, append them to `turn.state["research"]`,
     and loop until the model says "done" or the step budget runs out.

Result shape stored on the turn (consumed by codegen):

    turn.state["research"] = {
        "summary":   str,     # what the agent learned
        "steps":     [ { "tool": str, "params": dict, "result": <preview>,
                         "reason": str, "ok": bool, "error": str | null } ],
        "stopped":   "done" | "budget" | "no_safe_tool" | "loop"
    }
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from .executor import ApprovalDenied, Cancelled, Executor, ToolNotFound
from .llm import LLMClient, extract_json
from .tasks import TaskPlan, Turn
from .tools import Tool, ToolRegistry


log = logging.getLogger("huxform.researcher")


_SAFE_RISKS = {"read", "network", "write"}  # never auto-call destructive / filesystem / secret


def _safe_catalog(registry: ToolRegistry) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for t in registry.tools.values():
        if t.requires_approval:
            continue
        if t.risk not in _SAFE_RISKS:
            continue
        # task.* tools are for the iframe to call, not for research
        if t.name.startswith("task."):
            continue
        out.append({
            "name": t.name,
            "description": t.description,
            "params": t.params_schema,
            "risk": t.risk,
            "source": t.source,
        })
    return out


_SYSTEM = """You are HUXForm's Researcher.

You sit between the Director (which chose what to do and how it should look)
and the UI Generator (which renders the final interface). Your one job is to
gather real-world data so the generated UI is based on facts, not the LLM's
imagination.

Decision policy at each step:

  * If the task needs information from the outside world (current weather,
    package listings, repo contents, the contents of an attached file, an
    API response, etc.) — call ONE tool now.
  * Prefer batching less:
      - First call should usually be a search / list / fetch.
      - Follow-up calls should drill into the most promising URL or row.
  * If you have enough data for the UI Generator to render a real answer,
    stop with action="done" and a one-paragraph summary of what you learned.
  * If the task is purely about explaining a concept the LLM already knows
    well (e.g. "what is MCP?"), stop immediately with action="done" and a
    summary that the UI Generator will turn into the document.
  * If the task is purely visual / interactive with no real-world data
    dependency (e.g. "draw me a periodic table", "build me a stopwatch"),
    stop immediately — the UI Generator can do that alone.

NEVER call a tool you don't see in the catalog. NEVER guess parameter names —
match the schema exactly. If you make up a tool name, the call fails and you
waste a step.

You will be invoked one step at a time. Each turn return ONE of:

  { "action": "call",
    "tool":   "<name from the catalog>",
    "params": { ... matching params schema ... },
    "reason": "one short sentence — why this call advances the task" }

  { "action": "done",
    "summary": "what you found, in a paragraph the UI Generator can quote" }

Return ONE JSON object. No prose. No markdown fences.
"""


def _preview(value: Any, max_chars: int = 6000) -> Any:
    """Trim results before storing them on the turn (state is shipped over SSE
    and embedded in the codegen prompt — keep it small)."""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value if len(value) <= max_chars else value[: max_chars - 1] + "…"
    if isinstance(value, list):
        if len(value) <= 12:
            return [_preview(v, max_chars // 4) for v in value]
        return [_preview(v, max_chars // 4) for v in value[:12]] + [f"...(+{len(value) - 12} more)"]
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        budget = max_chars
        for k, v in list(value.items())[:24]:
            slot = max(200, budget // max(1, len(value)))
            out[str(k)] = _preview(v, slot)
            budget -= slot
        if len(value) > 24:
            out["…"] = f"(+{len(value) - 24} more keys)"
        return out
    # Fallback — coerce to string
    return _preview(str(value), max_chars)


class Researcher:
    def __init__(
        self,
        llm: LLMClient,
        registry: ToolRegistry,
        executor: Executor,
        *,
        max_steps: int = 5,
    ) -> None:
        self.llm = llm
        self.registry = registry
        self.executor = executor
        self.max_steps = max_steps

    async def research(
        self,
        turn: Turn,
        plan: TaskPlan,
        *,
        attached_files: list[dict] | None = None,
    ) -> dict[str, Any]:
        catalog = _safe_catalog(self.registry)
        steps: list[dict[str, Any]] = []
        seen: set[str] = set()
        stop_reason = "budget"
        summary: str | None = None

        turn.emit({"type": "research_started", "max_steps": self.max_steps})

        for step_idx in range(self.max_steps):
            if turn.cancelled:
                stop_reason = "cancelled"
                break

            decision = await self._decide_next(
                goal=turn.user_message,
                plan=plan,
                attached_files=attached_files or [],
                catalog=catalog,
                history=steps,
            )
            action = (decision.get("action") or "").lower()

            if action == "done":
                summary = str(decision.get("summary") or "").strip()
                stop_reason = "done"
                break

            if action != "call":
                # Bad output — treat as done to avoid hammering
                stop_reason = "done"
                break

            tool_name = str(decision.get("tool") or "").strip()
            params = decision.get("params") or {}
            reason = str(decision.get("reason") or "").strip()
            if not isinstance(params, dict):
                params = {}

            # Sanity-check tool name against the safe catalog
            tool = self.registry.get(tool_name)
            if tool is None:
                steps.append({
                    "tool": tool_name, "params": params, "reason": reason,
                    "ok": False, "error": f"unknown tool: {tool_name}", "result": None,
                })
                continue
            if tool.requires_approval or tool.risk not in _SAFE_RISKS or tool.name.startswith("task."):
                steps.append({
                    "tool": tool_name, "params": params, "reason": reason,
                    "ok": False, "result": None,
                    "error": f"tool {tool_name} is not allowed in research phase (risk={tool.risk})",
                })
                continue

            sig = f"{tool_name}::{json.dumps(params, sort_keys=True, ensure_ascii=False)}"
            if sig in seen:
                # Looping on the same call — abort
                stop_reason = "loop"
                break
            seen.add(sig)

            turn.emit({
                "type": "research_step",
                "step": step_idx + 1,
                "tool": tool_name,
                "reason": reason,
                "params_preview": _preview(params, 600),
            })

            entry: dict[str, Any] = {
                "tool": tool_name, "params": params, "reason": reason,
                "ok": False, "result": None, "error": None,
            }
            try:
                result = await self.executor.call(turn, tool_name, dict(params))
                entry["ok"] = True
                entry["result"] = _preview(result)
            except (ToolNotFound, ApprovalDenied) as exc:
                entry["error"] = str(exc) or exc.__class__.__name__
            except Cancelled:
                stop_reason = "cancelled"
                steps.append(entry)
                break
            except Exception as exc:  # pragma: no cover - opportunistic
                log.exception("research tool call %s failed", tool_name)
                entry["error"] = str(exc)
            steps.append(entry)

        # Synthesize a one-paragraph summary if the model didn't supply one
        if summary is None and steps:
            summary = await self._summarize(turn.user_message, plan, steps)

        research = {
            "summary": summary or "",
            "steps": steps,
            "stopped": stop_reason,
        }

        # Park on the turn so codegen / iframe can read via agui.getState()
        turn.state["research"] = research
        turn.emit({
            "type": "research_done",
            "steps": len(steps),
            "stopped": stop_reason,
            "summary": summary or "",
        })
        return research

    # ------------------------------------------------------------------ helpers

    async def _decide_next(
        self,
        *,
        goal: str,
        plan: TaskPlan,
        attached_files: list[dict],
        catalog: list[dict[str, Any]],
        history: list[dict[str, Any]],
    ) -> dict[str, Any]:
        ctx = {
            "user_goal": goal,
            "plan": {
                "task_type": plan.task_type,
                "presentation_mode": plan.presentation_mode,
                "visual_concept": plan.visual_concept,
                "steps": plan.steps,
                "tool_hints": plan.tool_hints,
                "needs_user_input": plan.needs_user_input,
            },
            "attached_files": attached_files,
            "tool_catalog": catalog,
            "research_so_far": history,
            "budget_remaining": max(0, self.max_steps - len(history)),
        }
        user = (
            "Decide the next research action.\n\n"
            "```json\n" + json.dumps(ctx, ensure_ascii=False, indent=2)[:14000] + "\n```\n"
            "\nReturn one JSON object with either action='call' (and tool/params/reason) "
            "or action='done' (and summary). Nothing else."
        )
        reply = await self.llm.complete(
            system=_SYSTEM,
            messages=[{"role": "user", "content": user}],
            temperature=0.2,
        )
        try:
            return extract_json(reply.text)
        except Exception:
            return {"action": "done", "summary": ""}

    async def _summarize(
        self, goal: str, plan: TaskPlan, steps: list[dict[str, Any]],
    ) -> str:
        if not steps:
            return ""
        digest = []
        for s in steps:
            slot = {
                "tool": s.get("tool"),
                "reason": s.get("reason"),
                "ok": s.get("ok"),
            }
            res = s.get("result")
            if isinstance(res, (dict, list)):
                slot["result"] = _preview(res, 2000)
            elif isinstance(res, str):
                slot["result"] = res[:2000]
            if s.get("error"):
                slot["error"] = s["error"]
            digest.append(slot)
        sys = (
            "You are HUXForm's Researcher. Summarize the research trail below in "
            "a single paragraph (4-7 sentences) the UI Generator can quote. State "
            "the concrete facts the user asked for (numbers, URLs, names) — do "
            "not narrate the process."
        )
        user = (
            f"User goal: {goal}\n"
            f"Task type: {plan.task_type}\n"
            f"Presentation: {plan.presentation_mode}\n"
            "Research trail:\n```json\n"
            + json.dumps(digest, ensure_ascii=False, indent=2)[:10000]
            + "\n```\n\nReturn one paragraph of plain text."
        )
        reply = await self.llm.complete(
            system=sys,
            messages=[{"role": "user", "content": user}],
            temperature=0.3,
        )
        return reply.text.strip()
