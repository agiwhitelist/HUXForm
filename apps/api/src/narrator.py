"""Narrator: turn raw events into short, human-friendly commentary.

A separate LLM call is too expensive per event. Instead we templatize
most events deterministically and only invoke the LLM at the few moments
where a sentence-long human summary makes a real difference (plan ready,
approval required, final result, failure).
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

from .llm import LLMClient
from .tasks import Turn


# Events that should produce a narration line.
_TEMPLATE_NARRATIONS: dict[str, Callable[[dict, Turn], str]] = {
    "task_created": lambda ev, t: f"AGUI received your request.",
    "planning_started": lambda ev, t: "Reading the task and choosing the right shape…",
    "codegen_started": lambda ev, t: "Designing an interface for this task…",
    "ui_ready": lambda ev, t: f"Interface ready ({ev.get('bytes', 0)} bytes). Starting work.",
    "running": lambda ev, t: "Now running.",
    "tool_called": lambda ev, t: f"Calling {ev.get('title') or ev.get('tool')}…",
    "tool_result": lambda ev, t: f"{ev.get('tool')} returned.",
    "tool_error": lambda ev, t: f"{ev.get('tool')} failed: {ev.get('message', '')}",
    "tool_denied": lambda ev, t: f"You denied {ev.get('tool')}.",
    "tool_dry_run": lambda ev, t: f"Dry-run of {ev.get('tool')} — no side effects.",
    "state_patch": lambda ev, t: _describe_state_patch(ev.get("patch") or {}),
    "log": lambda ev, t: f"· {ev.get('message', '')}",
    "cancelled": lambda ev, t: "Task cancelled.",
}


def _describe_state_patch(patch: dict) -> str:
    if not patch:
        return ""
    keys = list(patch.keys())[:3]
    return "State: " + ", ".join(f"{k}={_short(patch[k])}" for k in keys)


def _short(v: Any) -> str:
    s = str(v)
    return s if len(s) < 40 else s[:37] + "…"


class Narrator:
    """Subscribes to a turn's stream and re-emits compact `narration` events."""

    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    def attach(self, turn: Turn) -> asyncio.Task:
        return asyncio.create_task(self._run(turn))

    async def _run(self, turn: Turn) -> None:
        q = turn.subscribe()
        seen: set[str] = set()
        try:
            while True:
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=60.0)
                except asyncio.TimeoutError:
                    if turn.status in {"done", "failed", "cancelled"}:
                        return
                    continue
                t = ev.get("type")
                if t in {"narration", "heartbeat"}:
                    continue
                if t == "plan_ready":
                    await self._narrate_plan(turn, ev)
                elif t == "approval_required":
                    await self._narrate_approval(turn, ev)
                elif t == "final_result":
                    await self._narrate_final(turn, ev)
                elif t == "failed":
                    turn.emit({"type": "narration", "text": f"This task failed: {ev.get('message', '')}", "tone": "error"})
                elif t in _TEMPLATE_NARRATIONS:
                    text = _TEMPLATE_NARRATIONS[t](ev, turn)
                    if not text:
                        continue
                    # Avoid duplicate narrations for very fast tool sequences
                    sig = f"{t}:{text}"
                    if sig in seen and t in {"state_patch", "log"}:
                        continue
                    seen.add(sig)
                    turn.emit({"type": "narration", "text": text, "tone": "info"})
                if t in {"final_result", "failed", "cancelled"}:
                    return
        finally:
            turn.unsubscribe(q)

    async def _narrate_plan(self, turn: Turn, ev: dict) -> None:
        plan = ev.get("plan") or {}
        concept = plan.get("visual_concept", "")
        mode = plan.get("presentation_mode", "")
        rationale = plan.get("rationale", "")
        text = f"Plan: {mode} · {concept}. {rationale}".strip()
        turn.emit({"type": "narration", "text": text, "tone": "info"})

    async def _narrate_approval(self, turn: Turn, ev: dict) -> None:
        try:
            reply = await self.llm.complete(
                system=(
                    "You write a one-sentence explanation for a human about an action an AI "
                    "agent is about to take. Be specific, plain, and non-alarming. No emoji, "
                    "no fluff. Output the sentence only."
                ),
                messages=[{
                    "role": "user",
                    "content": (
                        f"Tool: {ev.get('tool_title') or ev.get('tool')}\n"
                        f"Risk class: {ev.get('risk')}\n"
                        f"Description: {ev.get('description', '')}\n"
                        f"Params preview: {ev.get('params_preview')}\n\n"
                        "One sentence:"
                    ),
                }],
                max_tokens=120,
                temperature=0.3,
            )
            text = reply.text.strip().splitlines()[0] if reply.text else f"Approve {ev.get('tool')}?"
        except Exception:
            text = f"Approve {ev.get('tool')}?"
        turn.emit({"type": "narration", "text": text, "tone": "warn", "approval_id": ev.get("approval_id")})

    async def _narrate_final(self, turn: Turn, ev: dict) -> None:
        text = "Done."
        result = ev.get("result")
        if isinstance(result, dict):
            for k in ("summary", "headline", "message"):
                if isinstance(result.get(k), str):
                    text = result[k]
                    break
        turn.emit({"type": "narration", "text": text, "tone": "success"})
