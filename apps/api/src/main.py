"""AGUI FastAPI entrypoint.

Endpoints:

  Threads:
    POST   /api/threads                            create thread (with first turn)
    GET    /api/threads                            list threads
    GET    /api/threads/{tid}                      thread + ordered turns

  Turns:
    POST   /api/threads/{tid}/turns                add a follow-up turn
    GET    /api/turns/{tid}                        snapshot
    GET    /api/turns/{tid}/ui                     generated HTML
    GET    /api/turns/{tid}/events                 SSE event stream (replayable)
    POST   /api/turns/{tid}/tools/{name}           run a tool (iframe bridge target)
    POST   /api/turns/{tid}/approve                resolve a pending approval
    POST   /api/turns/{tid}/proceed                signal "proceed past plan steering"
    POST   /api/turns/{tid}/cancel                 cancel a running turn

  Files:
    POST   /api/files                              upload a file
    GET    /api/files/{fid}                        download

  Tools:
    GET    /api/tools                              registered tools
    POST   /api/tools/openapi                      hot-register an OpenAPI spec

  Inspector:
    GET    /api/audit?turn_id=&limit=              audit tail
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import mimetypes
import os
import shutil
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from .audit import Audit
from .codegen import UIGenerator
from .director import Director
from .executor import ApprovalDenied, Cancelled, Executor, ToolNotFound
from .llm import LLMClient
from .mcp_client import MCPManager
from .narrator import Narrator
from .openapi_adapter import OpenAPIAdapter, OpenAPIRegistration
from .persistence import EventPersistor, Persistence
from .runtime import set_registry
from .runtime_stub import inject_runtime
from .tasks import FileRecord, Registry, Turn, stream_events
from .tools import register_builtin_tools


log = logging.getLogger("agui")


DATA_DIR = Path(os.environ.get("AGUI_DATA_DIR", ".huxform-data"))
FILES_DIR = DATA_DIR / "files"
DB_PATH = DATA_DIR / "agui.sqlite"
AUDIT_DB_PATH = DATA_DIR / "audit.sqlite"
MCP_CONFIG_PATH = Path(os.environ.get("AGUI_MCP_CONFIG", ".agui/mcp.json"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    FILES_DIR.mkdir(parents=True, exist_ok=True)

    llm = LLMClient()
    registry = Registry()
    set_registry(registry)

    persistence = Persistence(DB_PATH)
    persistence.hydrate(registry)
    registry.add_listener(persistence)

    audit = Audit(AUDIT_DB_PATH)

    tools = register_builtin_tools(llm)

    mcp = MCPManager(tools)
    try:
        await mcp.start_from_config(MCP_CONFIG_PATH)
    except Exception as exc:
        log.exception("MCP startup error: %s", exc)

    openapi = OpenAPIAdapter(tools)

    app.state.llm = llm
    app.state.registry = registry
    app.state.tools = tools
    app.state.persistence = persistence
    app.state.audit = audit
    app.state.mcp = mcp
    app.state.openapi = openapi
    app.state.director = Director(llm)
    app.state.codegen = UIGenerator(llm, tools)
    app.state.executor = Executor(tools)
    app.state.narrator = Narrator(llm)
    app.state.event_persistor = EventPersistor(persistence)

    try:
        yield
    finally:
        await mcp.stop_all()
        await openapi.aclose()
        await llm.aclose()
        persistence.close()
        audit.close()


app = FastAPI(title="HUXForm", version="0.3.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class CreateThreadBody(BaseModel):
    goal: str = Field(min_length=1, max_length=4000)
    title: str | None = None
    file_ids: list[str] = Field(default_factory=list)
    auto_proceed: bool = True


class AddTurnBody(BaseModel):
    goal: str = Field(min_length=1, max_length=4000)
    parent_turn_id: str | None = None
    file_ids: list[str] = Field(default_factory=list)
    auto_proceed: bool = True


class ApprovalBody(BaseModel):
    approval_id: str
    approved: bool


class RegenerateBody(BaseModel):
    refine_note: str | None = None


class OpenAPIRegisterBody(BaseModel):
    alias: str
    spec_url: str
    base_url: str = ""
    auth_header_name: str | None = None
    auth_header_value: str | None = None


# ---------------------------------------------------------------------------
# Health / tools / audit
# ---------------------------------------------------------------------------


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/tools")
async def list_tools(request: Request) -> dict[str, Any]:
    return {"tools": request.app.state.tools.bridge_schema()}


@app.post("/api/tools/openapi")
async def register_openapi(body: OpenAPIRegisterBody, request: Request) -> dict[str, Any]:
    adapter: OpenAPIAdapter = request.app.state.openapi
    auth = None
    if body.auth_header_name and body.auth_header_value:
        auth = (body.auth_header_name, body.auth_header_value)
    reg = OpenAPIRegistration(
        alias=body.alias,
        spec_url=body.spec_url,
        base_url=body.base_url or "",
        auth_header=auth,
    )
    try:
        n = await adapter.register_spec(reg)
    except Exception as exc:
        raise HTTPException(400, f"failed to load spec: {exc}")
    return {"ok": True, "registered": n}


@app.get("/api/audit")
async def get_audit(request: Request, turn_id: str | None = None, limit: int = 100) -> dict[str, Any]:
    return {"entries": request.app.state.audit.tail(turn_id=turn_id, limit=min(limit, 500))}


# ---------------------------------------------------------------------------
# Threads
# ---------------------------------------------------------------------------


@app.post("/api/threads")
async def create_thread(body: CreateThreadBody, request: Request) -> dict[str, Any]:
    state = request.app.state
    registry: Registry = state.registry
    title = (body.title or body.goal).strip().splitlines()[0][:80]
    thread = await registry.create_thread(title=title)
    turn = await registry.create_turn(
        thread_id=thread.id,
        user_message=body.goal,
        file_ids=body.file_ids or [],
    )
    turn.auto_proceed = body.auto_proceed
    asyncio.create_task(_drive_turn(turn, state))
    return {"thread_id": thread.id, "turn_id": turn.id}


@app.get("/api/threads")
async def list_threads(request: Request) -> dict[str, Any]:
    registry: Registry = request.app.state.registry
    threads = registry.list_threads()
    return {
        "threads": [
            {"id": t.id, "title": t.title, "created_at": t.created_at, "turn_count": len(t.turn_ids)}
            for t in threads
        ]
    }


@app.get("/api/threads/{thread_id}")
async def get_thread(thread_id: str, request: Request) -> dict[str, Any]:
    registry: Registry = request.app.state.registry
    thread = registry.get_thread(thread_id)
    if thread is None:
        raise HTTPException(404, "thread not found")
    turns = registry.list_thread_turns(thread_id)
    return {
        "id": thread.id,
        "title": thread.title,
        "created_at": thread.created_at,
        "turns": [_turn_snapshot(t, registry) for t in turns],
    }


@app.post("/api/threads/{thread_id}/turns")
async def add_turn(thread_id: str, body: AddTurnBody, request: Request) -> dict[str, Any]:
    state = request.app.state
    registry: Registry = state.registry
    thread = registry.get_thread(thread_id)
    if thread is None:
        raise HTTPException(404, "thread not found")
    turn = await registry.create_turn(
        thread_id=thread_id,
        user_message=body.goal,
        parent_turn_id=body.parent_turn_id,
        file_ids=body.file_ids or [],
    )
    turn.auto_proceed = body.auto_proceed
    asyncio.create_task(_drive_turn(turn, state))
    return {"turn_id": turn.id}


# ---------------------------------------------------------------------------
# Turns
# ---------------------------------------------------------------------------


@app.get("/api/turns/{turn_id}")
async def get_turn(turn_id: str, request: Request) -> dict[str, Any]:
    registry: Registry = request.app.state.registry
    turn = registry.get_turn(turn_id)
    if turn is None:
        raise HTTPException(404, "turn not found")
    return _turn_snapshot(turn, registry)


@app.get("/api/turns/{turn_id}/ui", response_class=HTMLResponse)
async def get_turn_ui(turn_id: str, request: Request) -> HTMLResponse:
    turn = request.app.state.registry.get_turn(turn_id)
    if turn is None:
        raise HTTPException(404, "turn not found")
    if turn.html is None:
        return HTMLResponse(_WAITING_HTML.replace("{{TURN_ID}}", turn_id), status_code=202)
    return HTMLResponse(inject_runtime(turn.html))


@app.get("/api/turns/{turn_id}/events")
async def turn_events(turn_id: str, request: Request):
    registry: Registry = request.app.state.registry
    turn = registry.get_turn(turn_id)
    if turn is None:
        raise HTTPException(404, "turn not found")

    # If the turn already has history persisted but no in-memory queue (because
    # the server restarted), hydrate the history into the turn before streaming.
    if not turn._history and turn.status in {"done", "failed", "cancelled"}:
        history = request.app.state.persistence.load_events(turn_id, limit=1000)
        for ev in history:
            turn._history.append(ev)

    async def gen():
        async for ev in stream_events(turn):
            if await request.is_disconnected():
                break
            yield {"event": ev.get("type", "message"), "data": json.dumps(ev, ensure_ascii=False, default=str)}

    return EventSourceResponse(gen())


@app.post("/api/turns/{turn_id}/tools/{tool_name}")
async def call_tool(turn_id: str, tool_name: str, request: Request) -> Any:
    state = request.app.state
    turn = state.registry.get_turn(turn_id)
    if turn is None:
        raise HTTPException(404, "turn not found")
    try:
        params = await request.json()
    except Exception:
        params = {}
    if not isinstance(params, dict):
        params = {"value": params}

    await state.audit.record(kind="tool_request", turn_id=turn_id, data={"tool": tool_name, "params": params})

    try:
        result = await state.executor.call(turn, tool_name, params)
    except ToolNotFound:
        raise HTTPException(404, f"unknown tool: {tool_name}")
    except ApprovalDenied:
        raise HTTPException(403, "approval denied")
    except Cancelled:
        raise HTTPException(499, "task cancelled")
    except Exception as exc:
        raise HTTPException(500, str(exc))

    await state.audit.record(kind="tool_result", turn_id=turn_id, data={"tool": tool_name, "ok": True})
    return {"ok": True, "result": result}


@app.post("/api/turns/{turn_id}/approve")
async def resolve_approval(turn_id: str, body: ApprovalBody, request: Request) -> dict[str, Any]:
    state = request.app.state
    turn = state.registry.get_turn(turn_id)
    if turn is None:
        raise HTTPException(404, "turn not found")
    ok = state.executor.resolve_approval(turn, body.approval_id, body.approved)
    if not ok:
        raise HTTPException(409, "approval already resolved or unknown")
    await state.audit.record(
        kind="approval", turn_id=turn_id,
        data={"approval_id": body.approval_id, "approved": body.approved},
    )
    return {"ok": True}


@app.post("/api/turns/{turn_id}/proceed")
async def proceed_turn(turn_id: str, request: Request) -> dict[str, Any]:
    turn = request.app.state.registry.get_turn(turn_id)
    if turn is None:
        raise HTTPException(404, "turn not found")
    turn.proceed()
    return {"ok": True}


@app.post("/api/turns/{turn_id}/cancel")
async def cancel_turn(turn_id: str, request: Request) -> dict[str, Any]:
    turn = request.app.state.registry.get_turn(turn_id)
    if turn is None:
        raise HTTPException(404, "turn not found")
    turn.cancel()
    await request.app.state.persistence.save_turn(turn)
    return {"ok": True}


@app.post("/api/turns/{turn_id}/regenerate")
async def regenerate_turn(turn_id: str, body: RegenerateBody, request: Request) -> dict[str, Any]:
    state = request.app.state
    turn = state.registry.get_turn(turn_id)
    if turn is None:
        raise HTTPException(404, "turn not found")
    if turn.plan is None:
        raise HTTPException(409, "turn has no plan to regenerate from")
    asyncio.create_task(_regenerate_turn(turn, state, body.refine_note))
    return {"ok": True}


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------


@app.post("/api/files")
async def upload_file(request: Request, file: UploadFile = File(...)) -> dict[str, Any]:
    registry: Registry = request.app.state.registry
    raw = await file.read()
    digest = hashlib.sha256(raw).hexdigest()[:24]
    fid = digest
    safe_name = file.filename or "upload"
    mime = file.content_type or mimetypes.guess_type(safe_name)[0] or "application/octet-stream"
    path = FILES_DIR / fid
    if not path.exists():
        path.write_bytes(raw)
    rec = FileRecord(
        id=fid,
        name=safe_name,
        mime=mime,
        size=len(raw),
        path=str(path),
        created_at=time.time(),
    )
    await registry.add_file(rec)
    return {"file": rec.to_public()}


@app.get("/api/files/{file_id}")
async def download_file(file_id: str, request: Request) -> FileResponse:
    rec = request.app.state.registry.get_file(file_id)
    if rec is None:
        raise HTTPException(404, "file not found")
    return FileResponse(rec.path, filename=rec.name, media_type=rec.mime)


class AttachFileBody(BaseModel):
    file_id: str


@app.post("/api/turns/{turn_id}/files")
async def attach_file_to_turn(turn_id: str, body: AttachFileBody, request: Request) -> dict[str, Any]:
    registry: Registry = request.app.state.registry
    persistence: Persistence = request.app.state.persistence
    turn = registry.get_turn(turn_id)
    if turn is None:
        raise HTTPException(404, "turn not found")
    rec = registry.get_file(body.file_id)
    if rec is None:
        raise HTTPException(404, "file not found")
    if body.file_id not in turn.file_ids:
        turn.file_ids.append(body.file_id)
        await persistence.save_turn(turn)
        turn.emit({
            "type": "file_attached",
            "file": rec.to_public(),
        })
    return {"ok": True, "file": rec.to_public()}


# ---------------------------------------------------------------------------
# Pipeline driver
# ---------------------------------------------------------------------------


async def _drive_turn(turn: Turn, state: Any) -> None:
    persistence: Persistence = state.persistence
    registry: Registry = state.registry
    state.narrator.attach(turn)
    state.event_persistor.attach(turn)

    try:
        turn.emit({"type": "turn_created", "turn_id": turn.id, "goal": turn.user_message})

        # 1. Direct (plan + visual brief)
        turn.status = "planning"
        turn.emit({"type": "planning_started"})
        if turn.cancelled:
            return
        attached = [registry.get_file(fid).to_public() for fid in turn.file_ids if registry.get_file(fid)]
        thread = registry.get_thread(turn.thread_id)
        prior = registry.list_thread_turns(turn.thread_id)[:-1] if thread else []
        thread_summary = _summarize_prior_turns(prior)

        directed = await state.director.direct(
            turn.user_message,
            attached_files=attached,
            thread_summary=thread_summary,
        )
        turn.plan = directed.plan
        turn.auto_proceed = turn.auto_proceed and directed.auto_proceed
        turn.emit({"type": "plan_ready", "plan": directed.plan.to_dict()})
        await persistence.save_turn(turn)

        # 2. answer_only short-circuit: no codegen, no iframe
        if directed.plan.presentation_mode == "answer_only" and directed.answer_text:
            turn.answer_text = directed.answer_text
            turn.status = "done"
            turn.emit({"type": "final_result", "result": {"answer": directed.answer_text}, "answer_only": True})
            await persistence.save_turn(turn)
            return

        # 3. Plan steering: pause for user proceed/cancel unless auto_proceed
        if not turn.auto_proceed:
            turn.status = "awaiting_steer"
            turn.emit({"type": "awaiting_steer"})
            ok = await turn.wait_for_steer(timeout=120.0)
            if not ok or turn.cancelled:
                if not turn.cancelled:
                    turn.cancel()
                return

        # 4. Codegen
        turn.status = "generating"
        turn.emit({"type": "codegen_started"})
        if turn.cancelled:
            return
        html, usage = await state.codegen.generate(
            goal=turn.user_message,
            plan=directed.plan,
            files=attached,
        )
        turn.html = html
        # naive cumulative usage
        for k, v in (usage or {}).items():
            try:
                turn.usage[k] = turn.usage.get(k, 0) + int(v)
            except (TypeError, ValueError):
                pass
        turn.emit({"type": "ui_ready", "bytes": len(html)})
        await persistence.save_turn(turn)

        # 5. Running — generated UI takes over via bridge.
        turn.status = "running"
        turn.emit({"type": "running"})

    except Exception as exc:
        log.exception("turn pipeline failed")
        turn.status = "failed"
        turn.error = str(exc)
        turn.emit({"type": "failed", "message": str(exc)})
        try:
            await persistence.save_turn(turn)
        except Exception:
            pass


async def _regenerate_turn(turn: Turn, state: Any, refine_note: str | None) -> None:
    persistence: Persistence = state.persistence
    registry: Registry = state.registry
    try:
        previous_html = turn.html
        turn.status = "generating"
        turn.emit({"type": "regenerating", "refine_note": refine_note})
        attached = [registry.get_file(fid).to_public() for fid in turn.file_ids if registry.get_file(fid)]
        html, usage = await state.codegen.generate(
            goal=turn.user_message,
            plan=turn.plan,
            files=attached,
            refine_note=refine_note,
            previous_html=previous_html,
        )
        turn.html = html
        for k, v in (usage or {}).items():
            try:
                turn.usage[k] = turn.usage.get(k, 0) + int(v)
            except (TypeError, ValueError):
                pass
        turn.emit({"type": "ui_ready", "bytes": len(html), "regenerated": True})
        turn.status = "running"
        turn.emit({"type": "running"})
        await persistence.save_turn(turn)
    except Exception as exc:
        log.exception("regenerate failed")
        turn.emit({"type": "tool_error", "tool": "regenerate", "message": str(exc)})


def _summarize_prior_turns(prior: list[Turn]) -> str | None:
    if not prior:
        return None
    parts: list[str] = []
    for t in prior[-3:]:
        parts.append(f"- user: {t.user_message[:120]}")
        if t.plan:
            parts.append(f"  → mode: {t.plan.presentation_mode}, concept: {t.plan.visual_concept}")
        if isinstance(t.final_result, dict):
            for k in ("summary", "headline"):
                v = t.final_result.get(k)
                if isinstance(v, str):
                    parts.append(f"  → result: {v[:120]}")
                    break
    return "\n".join(parts) if parts else None


def _turn_snapshot(turn: Turn, registry: Registry) -> dict[str, Any]:
    files = []
    for fid in turn.file_ids:
        rec = registry.get_file(fid)
        if rec:
            files.append(rec.to_public())
    return turn.to_snapshot(files=files)


_WAITING_HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>AGUI</title>
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
<div>AGUI is shaping an interface for this turn…</div>
<div class="muted">{{TURN_ID}}</div></div></body></html>"""
