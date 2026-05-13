"""UI Generator.

Given a plan + visual brief, produce a self-contained HTML document for
the iframe stage. Two design rules above all else:

  1. The output must implement the visual_brief faithfully — its palette,
     typography, layout metaphor, motion vocabulary and microcopy tone are
     not suggestions, they are constraints.

  2. The output must NOT look like a generic dark SaaS dashboard. We ban
     common defaults explicitly and force the model to commit to the
     metaphor selected by the Director.
"""

from __future__ import annotations

import json
from textwrap import dedent

from .llm import LLMClient, extract_html
from .tasks import TaskPlan
from .tools import ToolRegistry


BRIDGE_DOCS = dedent("""
The runtime exposes window.agui:

  agui.plan, agui.tools, agui.goal, agui.taskId, agui.files

  await agui.callTool(name, params)        // run a registered tool
  await agui.askApproval(label, details)   // request a one-off human OK (returns boolean)
  agui.setState(patch)                     // merge a JSON patch into task state
  agui.getState()                          // current state snapshot (sync, cached)
  agui.finalResult(value)                  // mark the task done with a result
  agui.log(level, message)                 // emit a log event
  agui.onEvent(handler)                    // subscribe to live task events
  agui.toast(message, kind)                // ephemeral toast (kind: 'info' | 'success' | 'error')

  await agui.readFile(file_id)             // read an attached file
                                           //   text → { text, name, mime, size }
                                           //   binary → { base64, name, mime, size }

Event objects look like:
  { type: 'tool_called'|'tool_result'|'tool_error'|'approval_required'
        |'state_patch'|'log'|'final_result'|'narration'|'plan_ready'|... ,
    ...payload }
""").strip()


SYSTEM_TEMPLATE = """You are AGUI's UI Generator.

Your output is the entire user-facing experience for ONE task. It will
render inside a sandboxed iframe and is the only thing the human sees
besides AGUI's own thin shell.

There are two failure modes you must avoid above everything else:

  1. Looking like a generic AI app. If a stranger glanced at your output
     and could not tell what task it serves, you have failed. The visual
     brief below dictates the look — implement it literally.

  2. Falling back to defaults. The visual_brief lists banned_patterns —
     do not produce them. If you find yourself reaching for a 3-column
     card grid, a sidebar with hamburger, an avatar in the top right, a
     plain 0–100 progress bar, or a glassmorphism panel — STOP. The
     metaphor demands something specific.

Hard technical rules:
  * Output ONLY one complete HTML document, starting with <!DOCTYPE html>.
    No markdown fences, no commentary before or after.
  * No external resources. No <script src=...>, no <link href=...>, no
    Google Fonts, no CDN, no images by URL. Inline SVG and CSS gradients
    only. System / web-safe font stacks only.
  * No fetch / no XHR / no WebSocket — the ONLY way to touch the world is
    through window.agui (documented below).
  * Subscribe to agui.onEvent at boot. Render plan steps, tool calls,
    state patches and final result LIVE. Do not show a static page.
  * If plan.needs_user_input is true, build the controls the user needs
    (file picker via agui.files, sliders, toggles, dropdowns, etc.).
    Otherwise the UI must drive itself: kick off the agent's plan from
    the boot script, reflect events as they arrive, and call
    agui.finalResult when done.
  * Stay self-contained, ≤ 36 KB total. Be concise.

Design contract — use the brief, not your defaults:

  metaphor:        {metaphor}
  presentation:    {mode}
  visual concept:  {concept}
  layout:          {layout}
  interaction:     {interaction}
  motion:          {motion}
  microcopy_tone:  {microcopy_tone}

  palette (use these EXACT hex values):
{palette}

  typography:
{typography}

  inspirations:
{inspirations}

  forbidden defaults (do not produce any of these):
{banned}

Bridge reference:
{bridge_docs}

Return the full HTML document only.
"""


def _format_kv(d: dict[str, str], indent: str = "    ") -> str:
    if not d:
        return f"{indent}(unspecified — invent something fitting the metaphor)"
    return "\n".join(f"{indent}{k}: {v}" for k, v in d.items())


def _format_list(items: list[str], indent: str = "    ") -> str:
    if not items:
        return f"{indent}(none)"
    return "\n".join(f"{indent}- {x}" for x in items)


class UIGenerator:
    def __init__(self, llm: LLMClient, registry: ToolRegistry) -> None:
        self.llm = llm
        self.registry = registry

    async def generate(
        self,
        *,
        goal: str,
        plan: TaskPlan,
        files: list[dict] | None = None,
        refine_note: str | None = None,
        previous_html: str | None = None,
    ) -> tuple[str, dict]:
        brief = plan.visual_brief
        if brief is None:
            # Fallback brief so codegen still has constraints
            brief_dict = {
                "metaphor": "a focused single-purpose tool, not a dashboard",
                "palette": {"bg": "#0f1116", "ink": "#e6e8ef", "accent": "#7aa2ff"},
                "typography": {"display": "system-ui", "body": "system-ui", "mono": "ui-monospace"},
                "layout": "single-column, generous whitespace",
                "interaction": "direct manipulation",
                "motion": "subtle",
                "microcopy_tone": "concise",
                "banned_patterns": [],
                "inspirations": [],
            }
        else:
            brief_dict = brief.to_dict()

        system = SYSTEM_TEMPLATE.format(
            metaphor=brief_dict.get("metaphor", ""),
            mode=plan.presentation_mode,
            concept=plan.visual_concept,
            layout=brief_dict.get("layout", ""),
            interaction=brief_dict.get("interaction", ""),
            motion=brief_dict.get("motion", ""),
            microcopy_tone=brief_dict.get("microcopy_tone", ""),
            palette=_format_kv(brief_dict.get("palette") or {}),
            typography=_format_kv(brief_dict.get("typography") or {}),
            inspirations=_format_list(brief_dict.get("inspirations") or []),
            banned=_format_list(brief_dict.get("banned_patterns") or []),
            bridge_docs=BRIDGE_DOCS,
        )

        user_payload = {
            "goal": goal,
            "plan": plan.to_dict(),
            "files": files or [],
            "tools": self.registry.bridge_schema(),
        }
        instruction = (
            "Build the AGUI experience for this task.\n\n"
            "```json\n" + json.dumps(user_payload, ensure_ascii=False, indent=2) + "\n```\n"
        )
        if refine_note:
            instruction += (
                "\nThis is a REGENERATION. The previous interface existed but the "
                "human asked for the following refinement — apply it without losing the "
                "metaphor, and produce a fresh complete document:\n\n"
                f"---\n{refine_note}\n---\n"
            )
        if previous_html and refine_note:
            preview = previous_html[:2400]
            instruction += (
                "\nHere is the start of the previous document for context (do NOT just "
                "copy it — reinterpret it through the refinement note):\n\n"
                f"```html\n{preview}\n```\n"
            )
        instruction += (
            "\nImplement the visual brief literally. Do not fall back to a generic dark "
            "card-grid dashboard. Return the full HTML document now."
        )
        user_msg = instruction
        reply = await self.llm.complete(
            system=system,
            messages=[{"role": "user", "content": user_msg}],
            temperature=0.75,
            max_tokens=8192,
        )
        html = extract_html(reply.text)
        usage = (reply.raw or {}).get("usage") or {}
        return html, usage
