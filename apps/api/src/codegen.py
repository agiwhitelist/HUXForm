"""UI Generator.

Given a Plan and the available tool capabilities, asks the LLM to emit a
complete, self-contained HTML document for the task. The document runs
inside a sandboxed iframe and talks to AGUI exclusively through
window.agui.* bridge calls. We don't constrain it to a component
library — every task gets its own micro-app.
"""

from __future__ import annotations

import json
from textwrap import dedent

from .llm import LLMClient, extract_html
from .tasks import TaskPlan
from .tools import ToolRegistry


BRIDGE_DOCS = dedent("""
The runtime exposes a single global, window.agui, with the following async API:

  await agui.callTool(name, params)        // Run a tool. Returns the tool's result.
  await agui.askApproval(label, details)   // Request a user OK for a custom action.
  agui.setState(patch)                     // Merge a JSON patch into task state (also: agui.callTool('task.set_state', {patch})).
  agui.getState()                          // Read the latest task state snapshot (sync, cached).
  agui.finalResult(value)                  // Mark the task complete with a result.
  agui.log(level, message)                 // Emit a log event (level: 'info' | 'warn' | 'error').
  agui.onEvent(handler)                    // Subscribe to live task events. Returns unsubscribe.
  agui.toast(message, kind)                // Show an ephemeral toast (kind: 'info' | 'success' | 'error').

Event objects look like:
  { type: 'tool_called' | 'tool_result' | 'tool_error' | 'tool_denied'
        | 'approval_required' | 'state_patch' | 'log' | 'final_result'
        | 'plan_ready' | 'heartbeat' | ... ,
    ...payload }

You also have agui.plan (the planner output) and agui.tools (capability list) available
synchronously at boot, plus agui.goal (the user's original intent string).
""").strip()


SYSTEM_TEMPLATE = """You are AGUI's UI Generator.

Your job: given a planned task and the available tool capabilities, write a
SINGLE self-contained HTML document that BECOMES the user-facing interface
for this specific task. It will be rendered inside a sandboxed iframe.

Hard rules:
  * Output ONLY a complete HTML document, starting with <!DOCTYPE html>.
    No commentary, no markdown fences, nothing before or after.
  * No external resources. No <script src=...>, no <link rel=stylesheet href=...>,
    no Google Fonts, no CDN. Everything inline.
  * No network requests of any kind from your JS. The ONLY way to do anything
    that touches the outside world is via window.agui (documented below).
  * The interface must MATCH the task. A CSV cleaner looks like a data
    workbench. A deploy console looks like a control room. A research task
    looks like a scouting radar. Pick a distinct visual identity per task —
    do not produce a generic "card grid".
  * Design for the chosen presentation_mode: {mode}. Visual concept: {concept}.
  * Subscribe to agui.onEvent at boot. Render progress, tool calls, logs, and
    final result LIVE — do not just dump a static page.
  * If needs_user_input is true, build the controls the user needs (upload,
    sliders, toggles, etc). Otherwise the UI should drive itself: kick off
    the agent's plan from the boot script and reflect events as they arrive.
  * Use modern, clean CSS. Dark theme by default. Be tasteful, not generic.
    Use system font stack. Smooth transitions for state changes. Empty
    states, loading states, error states all matter.
  * Keep total document under ~30KB. Be concise.

Bridge reference:
{bridge_docs}

Return ONLY the HTML document.
"""


class UIGenerator:
    def __init__(self, llm: LLMClient, registry: ToolRegistry) -> None:
        self.llm = llm
        self.registry = registry

    async def generate(self, *, goal: str, plan: TaskPlan) -> str:
        system = SYSTEM_TEMPLATE.format(
            mode=plan.presentation_mode,
            concept=plan.visual_concept,
            bridge_docs=BRIDGE_DOCS,
        )
        user_payload = {
            "goal": goal,
            "plan": {
                "task_type": plan.task_type,
                "presentation_mode": plan.presentation_mode,
                "visual_concept": plan.visual_concept,
                "rationale": plan.rationale,
                "steps": plan.steps,
                "tool_hints": plan.tool_hints,
                "needs_user_input": plan.needs_user_input,
            },
            "tools": self.registry.bridge_schema(),
        }
        user_msg = (
            "Build the AGUI experience for this task.\n\n"
            "```json\n" + json.dumps(user_payload, ensure_ascii=False, indent=2) + "\n```\n\n"
            "Return the full HTML document now."
        )
        reply = await self.llm.complete(
            system=system,
            messages=[{"role": "user", "content": user_msg}],
            temperature=0.7,
            max_tokens=8192,
        )
        return extract_html(reply.text)
