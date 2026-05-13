"""Director: combines Presentation Planning + Visual Direction in one pass.

Output is a Plan that includes a structured visual brief. The brief is
the antidote to "generic dark SaaS dashboard" — it forces the model to
commit to a specific metaphor, palette, layout and microcopy *before*
codegen ever runs.

We bias hard against templates by:
  * forbidding common defaults explicitly (banned_patterns),
  * requiring inspiration anchors that aren't software (newspaper front
    page, ham radio panel, museum label, control room, lab notebook),
  * demanding rationale for every design choice.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .llm import LLMClient, extract_json
from .tasks import TaskPlan, VisualBrief
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


SYSTEM = """You are AGUI's Director.

For every user intent you must decide:
  1. WHAT the agent will do — task type, presentation mode, steps, tool hints.
  2. HOW it will look — a complete visual brief that is SPECIFIC to this task,
     not a generic dark dashboard.

The single most important rule: the resulting interface must NOT look like
a templated AI app. AGUI's whole point is that every task gets its own
visual identity. If your brief sounds like it could be reused for any other
task, you have failed.

Output ONLY one JSON object with this schema:

{
  "task_type":         snake_case label, e.g. "csv_dedup", "deploy", "research_and_selection",
  "presentation_mode": one of [answer_only, status_view, progress_console, generated_app,
                                decision_board, approval_flow, report, dashboard, wizard,
                                debug_console, timeline],
  "visual_concept":    short distinctive name, e.g. "csv_cleaning_workbench",
                       "influencer_scouting_radar", "deploy_control_room", "rfq_ledger",
                       "manuscript_reading_room". One per task. Never reuse generic words
                       like 'dashboard', 'panel', 'view' on their own.
  "rationale":         one sentence — why this mode + concept fits this user,
  "steps":             3-8 short imperative phrases the agent will perform,
  "tool_hints":        list of tool names from the registry that you will likely call,
  "needs_user_input":  true if the user must upload / configure / select to proceed,
  "auto_proceed":      true if codegen can start immediately without confirming the plan
                       (false for destructive or ambiguous tasks),
  "answer_text":       only for presentation_mode = "answer_only" — the plain-text answer
                       (markdown allowed). Omit otherwise.

  "visual_brief": {
    "metaphor":          one sentence describing the spatial / sensory metaphor.
                         Reach OUTSIDE software for inspiration. Examples:
                           - "a bench-top duplicate-finder built like an analog mixing console
                              with horizontal rails of grouped specimens"
                           - "a circular sonar sweep with discovered influencers pinned on
                              concentric range rings, weighted by engagement"
                           - "a classified-document reading room: monospaced columns,
                              ticker tape of agent steps along the top, redaction blocks
                              around uncertain findings"
                         Forbidden: 'modern saas dashboard', 'minimalist card grid',
                         'standard chat UI', 'glassmorphism panels'.
    "palette":           object: hex colors keyed by semantic role —
                         {"bg":"#...", "bg_alt":"#...", "ink":"#...", "ink_dim":"#...",
                          "accent":"#...", "warn":"#...", "good":"#...", "danger":"#..."}.
                         Pick colors that fit the metaphor (a workshop is warm, a control
                         room is cold, a reading room is paper-tinted). DO NOT default to
                         #0b0d10 / #7aa2ff every time.
    "typography":        object: {"display":"font-family stack", "body":"...", "mono":"...",
                         "scale":"description of sizes and rhythm"}. Pick stacks that fit
                         the metaphor — a ledger uses serif, a control room uses a slab
                         monospace, a museum label uses humanist sans.
    "layout":            short description of the spatial composition (NOT 'sidebar +
                         main'). Be concrete: 'a horizontal rail of rows; metrics
                         pinned in the right gutter; sticky header with breath strip'.
    "interaction":       one or two sentences describing how the user moves through the
                         interface — what they click, what reacts where.
    "motion":            short description of the motion vocabulary (idle, transitions,
                         loading). Avoid generic 'smooth fades'.
    "microcopy_tone":    e.g. 'curt lab-tech', 'newsroom byline', 'pilot checklist',
                         'gallery curator'. Affects every label and message.
    "banned_patterns":   list of 4-8 specific defaults this UI must NOT use, e.g.
                         'three equal-width cards with rounded corners',
                         'avatar in top right',
                         'sidebar with hamburger menu',
                         'plain progress bar 0-100'.
    "inspirations":      list of 2-4 short non-software references —
                         'wartime sonar display', 'NYT election needle', 'old-school
                         spreadsheet ledger', 'control room of Apollo 11', 'radiology
                         film reading room'. Things from the real world.
  }
}

Hard rules:
  * If presentation_mode is "answer_only", visual_brief may be omitted (set null).
    Otherwise visual_brief is REQUIRED.
  * Be specific. Generic briefs produce generic UI.
  * No prose outside JSON. No markdown fences. JSON only.
"""


@dataclass
class DirectedPlan:
    plan: TaskPlan
    answer_text: str | None = None
    auto_proceed: bool = True


class Director:
    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    async def direct(
        self,
        goal: str,
        *,
        attached_files: list[dict] | None = None,
        thread_summary: str | None = None,
    ) -> DirectedPlan:
        ctx_lines: list[str] = [f"User intent:\n{goal}"]
        if attached_files:
            files_summary = "\n".join(
                f"  - {f['name']} ({f.get('mime', '?')}, {f['size']} bytes, id={f['id']})"
                for f in attached_files
            )
            ctx_lines.append(f"\nAttached files (accessible via files.read tool):\n{files_summary}")
        if thread_summary:
            ctx_lines.append(f"\nPrior context in this thread:\n{thread_summary}")
        ctx_lines.append(f"\nAvailable tool capabilities:\n{describe_tools()}")
        ctx_lines.append("\nReturn the Director JSON now.")
        user_msg = "\n".join(ctx_lines)

        reply = await self.llm.complete(
            system=SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
            temperature=0.55,
        )
        data = extract_json(reply.text)

        mode = str(data.get("presentation_mode", "")).strip()
        if mode not in PRESENTATION_MODES:
            mode = "status_view"

        brief = None
        raw_brief = data.get("visual_brief")
        if mode != "answer_only" and isinstance(raw_brief, dict):
            brief = VisualBrief(
                metaphor=str(raw_brief.get("metaphor") or ""),
                palette=dict(raw_brief.get("palette") or {}),
                typography=dict(raw_brief.get("typography") or {}),
                layout=str(raw_brief.get("layout") or ""),
                interaction=str(raw_brief.get("interaction") or ""),
                motion=str(raw_brief.get("motion") or ""),
                microcopy_tone=str(raw_brief.get("microcopy_tone") or ""),
                banned_patterns=[str(x) for x in (raw_brief.get("banned_patterns") or [])],
                inspirations=[str(x) for x in (raw_brief.get("inspirations") or [])],
            )

        plan = TaskPlan(
            task_type=str(data.get("task_type") or "general"),
            presentation_mode=mode,
            visual_concept=str(data.get("visual_concept") or f"{mode}_view"),
            rationale=str(data.get("rationale") or ""),
            steps=[str(s) for s in (data.get("steps") or []) if str(s).strip()],
            tool_hints=[str(t) for t in (data.get("tool_hints") or [])],
            needs_user_input=bool(data.get("needs_user_input", False)),
            visual_brief=brief,
        )

        answer_text = data.get("answer_text") if mode == "answer_only" else None
        auto = bool(data.get("auto_proceed", True))
        return DirectedPlan(plan=plan, answer_text=answer_text, auto_proceed=auto)
