"""Presentation Planner.

The planner decides, for a given user intent:
  * what kind of task this is,
  * which presentation mode best serves the human,
  * a concrete visual concept name for the generated UI,
  * the steps the agent will take,
  * which tool capabilities will be needed.

It is deliberately a *thin* layer: ask the LLM, parse JSON, validate.
"""

from __future__ import annotations

from .llm import LLMClient, extract_json
from .tasks import TaskPlan
from .tools import describe_tools

PRESENTATION_MODES = [
    "answer_only",
    "status_view",
    "progress_console",
    "generated_app",
    "decision_board",
    "approval_flow",
    "report",
    "dashboard",
    "wizard",
    "debug_console",
    "timeline",
]


SYSTEM = """You are AGUI's Presentation Planner.

AGUI is a generative human-experience runtime for AI agents. For every user
intent you must decide the SHAPE of the interaction — not just what to do,
but how a human should see it happen and consume the result.

You output ONLY a single JSON object with this exact schema:

{
  "task_type": short snake_case label, e.g. "csv_dedup", "deploy", "research_and_selection",
  "presentation_mode": one of [answer_only, status_view, progress_console, generated_app,
                               decision_board, approval_flow, report, dashboard, wizard,
                               debug_console, timeline],
  "visual_concept": a short distinctive name for the UI, e.g. "influencer_scouting_radar",
                    "csv_cleaning_workbench", "deploy_control_room". Be specific to THIS task,
                    not generic like "dashboard" or "form".
  "rationale": one short sentence explaining why this mode fits,
  "steps": ordered list of 3-8 concrete steps the agent will take, each a short imperative phrase,
  "tool_hints": list of capability names from the available tool registry that you will likely need,
  "needs_user_input": true if the user must upload/configure/select something to proceed,
                      false if the agent can run autonomously
}

Guiding principles:
  * Pick "answer_only" only for pure-knowledge questions where any UI would be noise.
  * Pick "generated_app" when the user has to upload, tune, or interact with results.
  * Pick "status_view" / "progress_console" when the agent runs autonomously and the human watches.
  * Pick "decision_board" for comparisons, "approval_flow" for destructive/irreversible actions,
    "report" when the deliverable is a document, "dashboard" for live monitoring.
  * Be specific in visual_concept. Each task deserves its own metaphor.

No prose, no markdown, no explanation outside JSON. Return JSON only.
"""


class PresentationPlanner:
    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    async def plan(self, goal: str) -> TaskPlan:
        user_msg = (
            f"User intent:\n{goal}\n\n"
            f"Available tool capabilities:\n{describe_tools()}\n\n"
            "Return the plan JSON now."
        )
        reply = await self.llm.complete(
            system=SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
            temperature=0.4,
        )
        data = extract_json(reply.text)
        mode = str(data.get("presentation_mode", "")).strip()
        if mode not in PRESENTATION_MODES:
            mode = "status_view"
        return TaskPlan(
            task_type=str(data.get("task_type") or "general"),
            presentation_mode=mode,
            visual_concept=str(data.get("visual_concept") or f"{mode}_view"),
            rationale=str(data.get("rationale") or ""),
            steps=[str(s) for s in (data.get("steps") or []) if str(s).strip()],
            tool_hints=[str(t) for t in (data.get("tool_hints") or [])],
            needs_user_input=bool(data.get("needs_user_input", False)),
        )
