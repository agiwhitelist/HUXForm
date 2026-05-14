"""Mission loop — multi-turn agentic execution toward one user goal.

The Researcher already gives every single turn a ReAct loop. A Mission is
the next layer up: it spans MULTIPLE turns. The LLM breaks the user's goal
into 3-7 step titles, then HUXForm spawns one child Turn per step,
auto-proceeds each, and waits for it to reach a terminal status before
moving on. Each step renders its own mini-app on the stage, so the user
watches the mission unfold as a sequence of generated experiences.

This is what idea.md calls a "Mission" — the gap between a single turn and
an agent that pursues a longer arc.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Awaitable, Callable

from .llm import LLMClient, extract_json
from .tasks import Mission, MissionStep, Registry, Turn


log = logging.getLogger("huxform.mission")


_PLANNER_SYSTEM = """You are HUXForm's Mission Planner.

The user gave you a goal that probably can't be completed in one shot.
Break it into 3-7 concrete steps the agent can execute one at a time.

Each step must:
  * be a self-contained task that produces its own visual interface (a
    research card, a comparison board, a wizard, a chart — whatever fits),
  * advance the overall goal,
  * be specific enough that the Director can pick a presentation mode
    without re-asking the user,
  * be ordered — earlier steps surface info later steps depend on.

Output ONLY one JSON object — no prose, no markdown fence:

{
  "steps": [
    {
      "title":  "<imperative phrase, ~6-10 words>",
      "detail": "<one sentence telling the next agent what specifically to do, including key search terms, names, or constraints from the user goal>"
    },
    ...
  ]
}

Guidelines for step count:
  * 3 steps for simple goals ("plan a weekend trip to Berlin")
  * 5-6 for layered ones ("pick + set up a payment processor for my SaaS")
  * 7 only when the arc clearly has that many distinct phases
"""


async def plan_mission_steps(llm: LLMClient, goal: str) -> list[MissionStep]:
    user = (
        f"User goal:\n{goal}\n\n"
        "Return the JSON now."
    )
    reply = await llm.complete(
        system=_PLANNER_SYSTEM,
        messages=[{"role": "user", "content": user}],
        temperature=0.3,
    )
    data = extract_json(reply.text)
    raw_steps = data.get("steps") if isinstance(data, dict) else None
    if not isinstance(raw_steps, list) or not raw_steps:
        # Fallback: one step = the whole goal
        return [MissionStep(title=goal.strip()[:120], detail=goal.strip())]
    out: list[MissionStep] = []
    for raw in raw_steps[:8]:
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("title") or "").strip()
        if not title:
            continue
        out.append(MissionStep(title=title[:160], detail=str(raw.get("detail") or "").strip()))
    if not out:
        return [MissionStep(title=goal.strip()[:120], detail=goal.strip())]
    return out


# DriveTurn signature: ``async def drive_turn(turn: Turn, state) -> None`` —
# the same coroutine main.py uses to run the per-turn pipeline. We accept it
# as a callable so this module doesn't depend on main.py at import time.
DriveTurn = Callable[[Turn, Any], Awaitable[None]]


async def drive_mission(
    mission: Mission,
    *,
    llm: LLMClient,
    registry: Registry,
    state: Any,
    drive_turn: DriveTurn,
    step_timeout: float = 600.0,
) -> None:
    """Plan + execute a mission. Updates mission.status / current_step /
    mission.steps[*].status as it goes. Each step gets its own Turn driven
    via the supplied drive_turn coroutine."""

    try:
        mission.status = "planning"
        mission.emit({"type": "mission_planning", "goal": mission.goal})

        steps = await plan_mission_steps(llm, mission.goal)
        mission.steps = steps
        mission.emit({
            "type": "mission_plan_ready",
            "steps": [s.to_dict() for s in mission.steps],
        })

        mission.status = "running"
        mission.emit({"type": "mission_started", "step_count": len(mission.steps)})

        for i, step in enumerate(mission.steps):
            if mission.cancelled:
                mission.status = "cancelled"
                mission.emit({"type": "mission_cancelled"})
                return
            mission.current_step = i
            step.status = "running"
            mission.emit({
                "type": "mission_step_started",
                "step": i,
                "title": step.title,
                "detail": step.detail,
            })

            child_goal = step.title
            if step.detail:
                child_goal += "\n\n" + step.detail

            turn = await registry.create_turn(
                thread_id=mission.thread_id,
                user_message=child_goal,
            )
            turn.auto_proceed = True
            # Stash mission linkage on the turn so the frontend can render
            # a per-turn "step N/M" badge.
            turn.state["mission"] = {
                "id": mission.id,
                "step": i,
                "of": len(mission.steps),
                "title": step.title,
            }
            step.turn_id = turn.id
            mission.emit({
                "type": "mission_step_turn_created",
                "step": i, "turn_id": turn.id,
            })

            # Kick off the per-turn pipeline as a background task so we
            # can await its terminal status separately.
            asyncio.create_task(drive_turn(turn, state))
            try:
                await asyncio.wait_for(_wait_terminal(turn), timeout=step_timeout)
            except asyncio.TimeoutError:
                step.status = "timeout"
                mission.emit({
                    "type": "mission_step_done",
                    "step": i, "status": "timeout", "turn_id": turn.id,
                })
                mission.status = "failed"
                mission.error = f"step {i + 1} timed out"
                return

            # `running` = codegen rendered, treat as success for mission.
            # `done`    = generated UI called agui.finalResult().
            success_states = {"running", "done"}
            step.status = "done" if turn.status in success_states else turn.status
            mission.emit({
                "type": "mission_step_done",
                "step": i, "status": step.status, "turn_id": turn.id,
            })

            if step.status != "done":
                mission.status = "failed"
                mission.error = f"step {i + 1} ended with status {turn.status}"
                return

        mission.status = "done"
        mission.emit({"type": "mission_done", "steps_completed": len(mission.steps)})

    except Exception as exc:
        log.exception("mission %s failed", mission.id)
        mission.status = "failed"
        mission.error = str(exc)
        mission.emit({"type": "mission_failed", "message": str(exc)})


async def _wait_terminal(turn: Turn) -> None:
    """Poll until a turn's mini-app has reached the stage.

    `running` means codegen finished and the iframe is rendering. We treat
    it as terminal for mission purposes — the step delivered its visual
    artifact and the mission can move on. The user can keep interacting
    with that step's UI; the mission just won't wait on it.

    `done` / `failed` / `cancelled` are also terminal in the obvious way.
    """
    terminal = {"running", "done", "failed", "cancelled"}
    while turn.status not in terminal:
        await asyncio.sleep(0.4)
    # Brief settle so the user can register the new step's UI appearing
    # before the next one fires.
    await asyncio.sleep(2.0)


async def stream_mission_events(mission: Mission):
    """SSE generator for a mission — replays history then streams live."""
    import time as _time
    q = mission.subscribe()
    terminal = {"mission_done", "mission_failed", "mission_cancelled"}
    already_done = mission.status in {"done", "failed", "cancelled"}
    while True:
        try:
            ev = await asyncio.wait_for(q.get(), timeout=20.0)
        except asyncio.TimeoutError:
            if already_done:
                return
            yield {"type": "heartbeat", "ts": _time.time()}
            continue
        yield ev
        if ev.get("type") in terminal:
            await asyncio.sleep(0.05)
            return
