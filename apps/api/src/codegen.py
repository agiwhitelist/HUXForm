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
  agui.research                          // server-side researcher results (see below)

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

  await agui.uploadFile(file)              // file = a File or Blob from <input type='file'>
                                           // returns { id, name, mime, size } — the new file
                                           // is automatically attached to this turn so you
                                           // can immediately call agui.readFile(id) or pass
                                           // it to tools.

agui.research shape (already gathered for you by the server before this UI
was rendered — render FROM it, do not invent data):

  {
    summary: "one paragraph describing what was learned",
    steps:   [ { tool, params, reason, ok, result, error } ],
    stopped: "done" | "budget" | "no_safe_tool" | "loop"
  }

  Typical patterns:
    - web.search result → steps[0].result.results is a list of { title, url, snippet }
    - web.fetch  result → steps[i].result has { url, title, text, description }
    - data.parse_csv   → { columns, rows, row_count }
    - data.find_duplicates → { groups: [ { key, count, rows } ] }
    - files.read       → { text } or { base64 }

How to take a file from the user (the iframe IS allowed forms, so a
plain <input type="file"> works — wire its onchange to agui.uploadFile):

  <input id="csv" type="file" accept=".csv,text/csv" />
  <script>
    document.getElementById('csv').addEventListener('change', async e => {
      const f = e.target.files[0];
      if (!f) return;
      const rec = await agui.uploadFile(f);                 // backend now has the file
      const data = await agui.readFile(rec.id);             // { text, name, mime, size }
      const parsed = await agui.callTool('data.parse_csv', { text: data.text });
      // ...render rows
    });
  </script>

Event objects look like:
  { type: 'tool_called'|'tool_result'|'tool_error'|'approval_required'
        |'state_patch'|'log'|'final_result'|'narration'|'plan_ready'|... ,
    ...payload }
""").strip()


SYSTEM_TEMPLATE = """You are HUXForm's UI Generator.

Your output is the ENTIRE user-facing experience for ONE task. It renders
inside a sandboxed iframe and is the only thing the human sees besides
HUXForm's thin shell. There is no "answer text" elsewhere — if a fact, hint,
caveat or follow-up exists, it lives inside the document you write.

Three failure modes you must avoid above everything else:

  1. Looking like a generic AI app. If a stranger glanced at your output
     and could not tell what task it serves, you have failed. Implement
     the visual brief literally.

  2. Falling back to defaults. The brief lists banned_patterns — produce
     none of them. If you reach for a 3-column card grid, a sidebar with
     a hamburger, an avatar in the top right, a plain 0–100 progress bar,
     or a glassmorphism panel, STOP and use the metaphor instead.

  3. Decorative, non-functional UI. Every button, slider, dropdown, file
     input, switch, search box you draw MUST be wired to a real handler
     using window.agui (callTool / uploadFile / readFile / setState / …).
     A button that does nothing is a bug. Read the bridge docs below and
     bind every interactive element to a real action before you ship the
     document.

  4. Hallucinated content. If `agui.research` (the server-side researcher
     output) is non-empty, you MUST render the document from those facts —
     names, URLs, numbers, snippets, rows. Do NOT invent plausible-looking
     data. If a section needs data that wasn't fetched, leave a clear empty
     state ("no data yet — agent will fill this") and either call the right
     tool yourself in the boot script or wait for events.

Hard technical rules:
  * Output ONLY one complete HTML document, starting with <!DOCTYPE html>.
    No markdown fences, no commentary before or after.
  * Allowed external resources are font CDNs ONLY — you may use
    <link rel="preconnect" href="https://fonts.googleapis.com">,
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    and one <link rel="stylesheet"
    href="https://fonts.googleapis.com/css2?family=..."> tag to pull the
    fonts named in the typography section. Nothing else from the network:
    no script CDN, no <img src="https://...">, no remote SVG. Images must
    be inline SVG or data: URLs.
  * No fetch / no XHR / no WebSocket from your script — the ONLY way to
    reach the backend, tools, or files is window.agui (documented below).
    Browser file pickers (<input type="file">) DO work in this sandbox;
    wire onchange to agui.uploadFile to send the file to the backend.
  * Read agui.research at boot. Quote real facts from steps[*].result and
    summary inside the document. Subscribe to agui.onEvent at boot too — render
    plan steps, tool calls, state patches and the final result LIVE. Never
    show a static page.
  * If `agui.research` is empty AND the task needs real data
    (search, fetch, list, compare, monitor, etc), call the appropriate
    tool yourself in the boot script — e.g.
        const r = await agui.callTool('web.search', {{ query: agui.goal, limit: 8 }});
        renderResults(r.results);
    Do NOT show stale or invented data while waiting.
  * If plan.needs_user_input is true OR agui.files is empty for a task
    that obviously requires data (csv_dedup, audit, parse_*, etc.), build
    a real file picker bound to agui.uploadFile, plus any sliders /
    toggles / dropdowns that affect the analysis. Validate empty states.
    Otherwise the UI drives itself: kick off the agent's plan in the
    boot script, reflect events as they arrive, and call agui.finalResult
    when finished.
  * Stay self-contained, ≤ 90 KB total HTML/CSS/JS. Be generous with
    layout, type, motion and SVG illustration — this is a hero document,
    not a low-fi wireframe. No external JS. No emoji as load-bearing
    icons; draw inline SVGs instead.
  * Style ambition: this document should look like a piece of bespoke
    software a senior designer made on purpose. Use the palette, real
    hierarchy, a display typeface, generous whitespace, a single focal
    composition. Avoid centered hero text on a blank page — fill the
    surface with the structure of the task.

  * Resilience: render even when expected state is missing. Guard every
    array access (use `Array.isArray(x) ? x.map(...) : null` or default
    `[]`), every property dereference (`obj?.field ?? defaultValue`), and
    wrap your boot script in try/catch so a malformed event never wipes
    the page. Show a quiet "no data yet" affordance instead of throwing.

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
        research: dict | None = None,
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
            "research": research or {},
        }
        instruction = (
            "Build the HUXForm experience for this task.\n\n"
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
            temperature=0.85,
            max_tokens=16384,
        )
        html = extract_html(reply.text)
        usage = (reply.raw or {}).get("usage") or {}
        return html, usage
