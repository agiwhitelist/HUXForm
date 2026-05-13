"""AGUI FastAPI entrypoint.

Endpoints:
  POST /api/tasks                          create a task from user intent
  GET  /api/tasks/{id}                     fetch task snapshot (plan, status, state)
  GET  /api/tasks/{id}/ui                  return the generated HTML document
  GET  /api/tasks/{id}/events              SSE stream of TaskEvents
  POST /api/tasks/{id}/tools/{name}        execute a tool (bridge target)
  POST /api/tasks/{id}/approve             resolve a pending approval
  GET  /api/tools                          list tool capabilities

The generated UI lives in apps/web; it loads the HTML for /ui/{id} into a
sandboxed iframe and proxies window.agui.* calls to the endpoints above.
"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from .codegen import UIGenerator
from .executor import ApprovalDenied, Executor, ToolNotFound
from .llm import LLMClient
from .planner import PresentationPlanner
from .runtime_stub import inject_runtime
from .tasks import Task, TaskRegistry, stream_events
from .tools import register_builtin_tools


log = logging.getLogger("agui")


@asynccontextmanager
async def lifespan(app: FastAPI):
    llm = LLMClient()
    app.state.llm = llm
    app.state.tools = register_builtin_tools(llm)
    app.state.tasks = TaskRegistry()
    app.state.planner = PresentationPlanner(llm)
    app.state.codegen = UIGenerator(llm, app.state.tools)
    app.state.executor = Executor(app.state.tools)
    try:
        yield
    finally:
        await llm.aclose()


app = FastAPI(title="AGUI", version="0.2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class CreateTaskBody(BaseModel):
    goal: str = Field(min_length=1, max_length=4000)


class ApprovalBody(BaseModel):
    approval_id: str
    approved: bool


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/tools")
async def list_tools(request: Request) -> dict[str, Any]:
    return {"tools": request.app.state.tools.bridge_schema()}


@app.post("/api/tasks")
async def create_task(body: CreateTaskBody, request: Request) -> dict[str, Any]:
    state = request.app.state
    task: Task = await state.tasks.create(body.goal)
    asyncio.create_task(_drive_task(task, state))
    return {"task_id": task.id}


@app.get("/api/tasks/{task_id}")
async def get_task(task_id: str, request: Request) -> dict[str, Any]:
    task = request.app.state.tasks.get(task_id)
    if task is None:
        raise HTTPException(404, "task not found")
    return _task_snapshot(task)


@app.get("/api/tasks/{task_id}/ui", response_class=HTMLResponse)
async def get_task_ui(task_id: str, request: Request) -> Response:
    task = request.app.state.tasks.get(task_id)
    if task is None:
        raise HTTPException(404, "task not found")
    if task.html is None:
        # Polite waiting page so the iframe has something to show while codegen runs
        return HTMLResponse(_WAITING_HTML.replace("{{TASK_ID}}", task_id), status_code=202)
    return HTMLResponse(inject_runtime(task.html))


@app.get("/api/tasks/{task_id}/events")
async def task_events(task_id: str, request: Request):
    task = request.app.state.tasks.get(task_id)
    if task is None:
        raise HTTPException(404, "task not found")

    async def gen():
        async for ev in stream_events(task):
            if await request.is_disconnected():
                break
            yield {"event": ev.get("type", "message"), "data": json.dumps(ev, ensure_ascii=False, default=str)}

    return EventSourceResponse(gen())


@app.post("/api/tasks/{task_id}/tools/{tool_name}")
async def call_tool(task_id: str, tool_name: str, request: Request) -> Any:
    state = request.app.state
    task = state.tasks.get(task_id)
    if task is None:
        raise HTTPException(404, "task not found")
    try:
        params = await request.json()
    except Exception:
        params = {}
    if not isinstance(params, dict):
        params = {"value": params}
    try:
        result = await state.executor.call(task, tool_name, params)
    except ToolNotFound:
        raise HTTPException(404, f"unknown tool: {tool_name}")
    except ApprovalDenied:
        raise HTTPException(403, "approval denied")
    return {"ok": True, "result": result}


@app.post("/api/tasks/{task_id}/approve")
async def resolve_approval(task_id: str, body: ApprovalBody, request: Request) -> dict[str, Any]:
    state = request.app.state
    task = state.tasks.get(task_id)
    if task is None:
        raise HTTPException(404, "task not found")
    ok = state.executor.resolve_approval(task, body.approval_id, body.approved)
    if not ok:
        raise HTTPException(409, "approval already resolved or unknown")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Background pipeline: plan -> codegen -> mark running
# ---------------------------------------------------------------------------


async def _drive_task(task: Task, state: Any) -> None:
    try:
        task.emit({"type": "task_created", "task_id": task.id, "goal": task.goal})

        task.status = "planning"
        task.emit({"type": "planning_started"})
        plan = await state.planner.plan(task.goal)
        task.plan = plan
        task.emit({
            "type": "plan_ready",
            "plan": {
                "task_type": plan.task_type,
                "presentation_mode": plan.presentation_mode,
                "visual_concept": plan.visual_concept,
                "rationale": plan.rationale,
                "steps": plan.steps,
                "tool_hints": plan.tool_hints,
                "needs_user_input": plan.needs_user_input,
            },
        })

        task.status = "generating"
        task.emit({"type": "codegen_started"})
        html = await state.codegen.generate(goal=task.goal, plan=plan)
        task.html = html
        task.emit({"type": "ui_ready", "bytes": len(html)})

        task.status = "running"
        task.emit({"type": "running"})
    except Exception as exc:
        log.exception("task pipeline failed")
        task.status = "failed"
        task.error = str(exc)
        task.emit({"type": "failed", "message": str(exc)})


def _task_snapshot(task: Task) -> dict[str, Any]:
    plan = None
    if task.plan is not None:
        p = task.plan
        plan = {
            "task_type": p.task_type,
            "presentation_mode": p.presentation_mode,
            "visual_concept": p.visual_concept,
            "rationale": p.rationale,
            "steps": p.steps,
            "tool_hints": p.tool_hints,
            "needs_user_input": p.needs_user_input,
        }
    return {
        "id": task.id,
        "goal": task.goal,
        "status": task.status,
        "plan": plan,
        "state": task.state,
        "final_result": task.final_result,
        "error": task.error,
        "has_ui": task.html is not None,
    }


_WAITING_HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>AGUI · planning</title>
<style>
  :root { color-scheme: dark; }
  html,body{margin:0;height:100%;background:#0b0d10;color:#e7e9ee;
    font-family:ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,sans-serif;}
  .wrap{display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;gap:14px;}
  .pulse{width:46px;height:46px;border-radius:50%;background:radial-gradient(circle,#7aa2ff,#3050b0 70%,#0b0d10 100%);
    animation:p 1.4s ease-in-out infinite;}
  @keyframes p{0%,100%{transform:scale(.85);opacity:.7}50%{transform:scale(1.05);opacity:1}}
  .muted{opacity:.6;font-size:13px}
</style></head>
<body><div class="wrap"><div class="pulse"></div>
<div>AGUI is shaping an interface for your task…</div>
<div class="muted">{{TASK_ID}}</div></div></body></html>"""
