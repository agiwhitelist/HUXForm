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
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from .audit import Audit
from .codegen import UIGenerator
from .director import Director
from .discovery import CapabilityRegistry, hydrate_installed
from .executor import ApprovalDenied, Cancelled, Executor, ToolNotFound
from .llm import LLMClient
from .mcp_client import MCPManager
from .narrator import Narrator
from .openapi_adapter import OpenAPIAdapter, OpenAPIRegistration
from .mission import drive_mission, stream_mission_events
from .persistence import EventPersistor, Persistence
from .researcher import Researcher
from .runtime import set_registry
from .runtime_stub import RUNTIME_STUB, inject_runtime
from .tasks import FileRecord, Mission, Registry, Turn, stream_events
from .tools import get_registry, register_builtin_tools


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

    capability_registry = CapabilityRegistry(DATA_DIR / "capability_registry.json")

    # Single ToolRegistry instance shared by builtin tools, the MCP manager,
    # and the OpenAPI adapter. Builtin tools are populated first; MCP /
    # OpenAPI / capability-registry hydration append additional entries.
    tools = get_registry()
    mcp = MCPManager(tools)
    register_builtin_tools(
        llm,
        mcp_manager=mcp,
        capability_registry=capability_registry,
    )

    try:
        await mcp.start_from_config(MCP_CONFIG_PATH)
    except Exception as exc:
        log.exception("MCP startup error: %s", exc)

    try:
        n = await hydrate_installed(mcp, capability_registry)
        if n:
            log.info("hydrated %d MCP tools from capability registry", n)
    except Exception as exc:
        log.exception("capability registry hydrate error: %s", exc)

    openapi = OpenAPIAdapter(tools)

    app.state.llm = llm
    app.state.registry = registry
    app.state.tools = tools
    app.state.persistence = persistence
    app.state.audit = audit
    app.state.mcp = mcp
    app.state.openapi = openapi
    app.state.capability_registry = capability_registry
    app.state.director = Director(llm)
    app.state.codegen = UIGenerator(llm, tools)
    app.state.executor = Executor(tools)
    app.state.researcher = Researcher(llm, tools, app.state.executor, max_steps=5)
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


class CreateMissionBody(BaseModel):
    goal: str = Field(min_length=1, max_length=4000)


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


# ---------------------------------------------------------------------------
# Streaming codegen: the iframe loads /ui-stream as soon as codegen starts.
# The endpoint subscribes to the turn's event queue, yields HTML to the
# response as `codegen_chunk` events arrive — minus any <script> blocks,
# which we defer until the stream closes so half-written JS can't run. At
# the end we flush the runtime stub + every deferred script + closing tags.
# The browser renders the response progressively (native HTML streaming),
# which is what kills the per-chunk srcDoc flicker.
# ---------------------------------------------------------------------------


class _ScriptStripper:
    """Stream HTML, hold back complete <script> blocks for the final flush.

    Also strips any leading ```html / ``` markdown fence the LLM might wrap
    the document in even when we tell it not to (some providers ignore the
    instruction).
    """

    def __init__(self) -> None:
        self.deferred: list[str] = []
        self.buffer: str = ""
        self._fence_handled = False
        self._sent_any = False

    def feed(self, chunk: str) -> str:
        self.buffer += chunk

        # Strip leading ```html / ``` fence the very first time we have
        # something to look at. Wait until we have at least a few chars so
        # we don't drop them prematurely.
        if not self._fence_handled and len(self.buffer) >= 8:
            stripped = self.buffer.lstrip()
            if stripped.startswith("```"):
                # Drop the opening fence (up to and including the first \n).
                lead = self.buffer.index("```")
                nl = self.buffer.find("\n", lead)
                if nl > -1:
                    self.buffer = self.buffer[nl + 1:]
                    self._fence_handled = True
                # else: not enough data yet, wait
            else:
                self._fence_handled = True

        out: list[str] = []
        while self.buffer:
            lower = self.buffer.lower()
            i = lower.find("<script")
            if i < 0:
                out.append(self.buffer)
                self.buffer = ""
                break
            # Everything before the next <script> is safe to flush.
            if i > 0:
                out.append(self.buffer[:i])
                self.buffer = self.buffer[i:]
            j = self.buffer.lower().find("</script>")
            if j < 0:
                # Script block is incomplete — wait for more chunks.
                break
            end = j + len("</script>")
            self.deferred.append(self.buffer[:end])
            self.buffer = self.buffer[end:]
        joined = "".join(out)
        if joined:
            self._sent_any = True
        return joined

    def finalize_safe_tail(self) -> str:
        rest = self.buffer
        self.buffer = ""
        # Drop trailing ``` fence if the LLM closed the markdown block.
        rest = rest.rstrip()
        if rest.endswith("```"):
            rest = rest[:-3].rstrip()
        if rest.lower().lstrip().startswith("<script"):
            # Incomplete trailing script — drop it.
            return ""
        return rest

    def deferred_scripts(self) -> str:
        return "".join(self.deferred)


def _build_stream_opener(turn: Turn) -> str:
    """Open the streamed HTML doc with the turn's brief palette baked into
    a default body style + a small loading shimmer. We also pad the response
    with a >=1 KB comment because most browsers buffer the first kilobyte of
    a chunked text/html response before committing to incremental rendering.
    Without the pad, iframes can show a black void for several seconds even
    though bytes are arriving."""
    bg = "#0b0d10"
    ink = "#e6e8ef"
    accent = "#7aa2ff"
    plan = turn.plan
    concept = ""
    if plan:
        concept = (plan.visual_concept or "").replace("_", " ")
        if plan.visual_brief and isinstance(plan.visual_brief.palette, dict):
            pal = plan.visual_brief.palette
            bg = str(pal.get("bg") or pal.get("background") or bg)
            ink = str(pal.get("ink") or pal.get("foreground") or pal.get("text") or ink)
            accent = str(pal.get("accent") or pal.get("signal") or accent)
    # Pad to ~1.2 KB so Chrome/Firefox/Safari commit to incremental render
    pad = "<!-- " + ("·" * 200) + " -->\n"
    opener = (
        "<!DOCTYPE html>\n"
        "<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<title>HUXForm</title>\n"
        "<style>\n"
        "  html,body{margin:0;min-height:100vh;font:14px/1.5 ui-sans-serif,system-ui,sans-serif;}\n"
        f"  html,body{{background:{bg};color:{ink};}}\n"
        "  .__huxform_boot{position:fixed;inset:0;display:grid;place-items:center;pointer-events:none;}\n"
        "  .__huxform_boot div{font-family:ui-monospace,Menlo,monospace;font-size:11px;letter-spacing:.22em;text-transform:uppercase;opacity:.5;}\n"
        f"  .__huxform_boot div::after{{content:' ▍';color:{accent};animation:__huxform_blink 700ms steps(1) infinite;}}\n"
        "  @keyframes __huxform_blink{50%{opacity:0;}}\n"
        "</style>\n"
        "<body>\n"
        f"<div class=\"__huxform_boot\"><div>drawing {concept or 'interface'}…</div></div>\n"
        f"{pad}"
    )
    return opener


_STREAM_CLOSER = "\n</body>\n</html>\n"


@app.get("/api/turns/{turn_id}/ui-stream")
async def get_turn_ui_stream(turn_id: str, request: Request) -> StreamingResponse:
    registry: Registry = request.app.state.registry
    turn = registry.get_turn(turn_id)
    if turn is None:
        raise HTTPException(404, "turn not found")

    async def gen():
        # If the turn is already complete, hand the iframe the cached HTML
        # in one shot — no need to stream.
        if turn.html and turn.status in {"running", "done", "failed", "cancelled"}:
            yield inject_runtime(turn.html)
            return

        # Tiny opener so the iframe paints a palette-tinted background
        # instead of staying black while the LLM warms up. The doctype +
        # meta are harmless duplicates of whatever the model later emits.
        yield _build_stream_opener(turn)

        stripper = _ScriptStripper()
        prev_sent = 0
        first_content_seen = False
        q = turn.subscribe()
        try:
            terminal_seen = False
            while not terminal_seen:
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=45.0)
                except asyncio.TimeoutError:
                    # If a terminal status snuck through without a stream
                    # event (e.g. crashed before codegen_started), bail.
                    if turn.status in {"failed", "cancelled"}:
                        break
                    # Heartbeat as an HTML comment so the connection stays
                    # warm without affecting layout.
                    yield "<!-- hb -->"
                    continue
                etype = ev.get("type")
                if etype == "codegen_chunk":
                    full = str(ev.get("html") or "")
                    if len(full) <= prev_sent:
                        continue
                    delta = full[prev_sent:]
                    prev_sent = len(full)
                    safe = stripper.feed(delta)
                    if safe:
                        # Hide the boot indicator only once the LLM has
                        # actually opened its <body> — before that the
                        # stream is just doctype + head + styles which
                        # are invisible, so the boot indicator should
                        # stay up to give the user a focal point.
                        if not first_content_seen and "<body" in full.lower():
                            yield "<style>.__huxform_boot{display:none!important;}</style>\n"
                            first_content_seen = True
                        yield safe
                elif etype in {"ui_ready", "regenerated"}:
                    terminal_seen = True
                elif etype in {"failed", "cancelled"}:
                    yield f"<!-- stream halted: {etype} -->"
                    terminal_seen = True
        finally:
            try:
                turn.unsubscribe(q)
            except Exception:
                pass

        # Flush any trailing safe text we held back (anything that wasn't
        # the start of a script block).
        tail = stripper.finalize_safe_tail()
        if tail:
            yield tail

        # Inject the runtime stub BEFORE the deferred scripts so window.agui
        # is alive by the time the LLM's scripts run.
        yield RUNTIME_STUB
        yield stripper.deferred_scripts()
        yield _STREAM_CLOSER

    return StreamingResponse(
        gen(),
        media_type="text/html; charset=utf-8",
        headers={
            "X-Accel-Buffering": "no",  # disable proxy buffering when behind nginx
            "Cache-Control": "no-store",
        },
    )


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


# ---------------------------------------------------------------------------
# Missions
# ---------------------------------------------------------------------------


@app.post("/api/threads/{thread_id}/missions")
async def create_mission(thread_id: str, body: CreateMissionBody, request: Request) -> dict[str, Any]:
    state = request.app.state
    registry: Registry = state.registry
    thread = registry.get_thread(thread_id)
    if thread is None:
        raise HTTPException(404, "thread not found")
    mission = await registry.create_mission(thread_id=thread_id, goal=body.goal)
    asyncio.create_task(drive_mission(
        mission,
        llm=state.llm,
        registry=registry,
        state=state,
        drive_turn=_drive_turn,
    ))
    return {"mission_id": mission.id, "thread_id": thread_id}


@app.get("/api/missions/{mission_id}")
async def get_mission(mission_id: str, request: Request) -> dict[str, Any]:
    registry: Registry = request.app.state.registry
    mission = registry.get_mission(mission_id)
    if mission is None:
        raise HTTPException(404, "mission not found")
    return mission.to_dict()


@app.get("/api/missions/{mission_id}/events")
async def mission_events(mission_id: str, request: Request):
    registry: Registry = request.app.state.registry
    mission = registry.get_mission(mission_id)
    if mission is None:
        raise HTTPException(404, "mission not found")

    async def gen():
        async for ev in stream_mission_events(mission):
            if await request.is_disconnected():
                break
            yield {"event": ev.get("type", "message"), "data": json.dumps(ev, ensure_ascii=False, default=str)}

    return EventSourceResponse(gen())


@app.post("/api/missions/{mission_id}/cancel")
async def cancel_mission(mission_id: str, request: Request) -> dict[str, Any]:
    registry: Registry = request.app.state.registry
    mission = registry.get_mission(mission_id)
    if mission is None:
        raise HTTPException(404, "mission not found")
    mission.cancelled = True
    return {"ok": True, "status": mission.status}


@app.get("/api/threads/{thread_id}/missions")
async def list_thread_missions(thread_id: str, request: Request) -> dict[str, Any]:
    registry: Registry = request.app.state.registry
    if registry.get_thread(thread_id) is None:
        raise HTTPException(404, "thread not found")
    missions = registry.list_thread_missions(thread_id)
    return {"missions": [m.to_dict() for m in sorted(missions, key=lambda m: m.created_at, reverse=True)]}


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

        # 4. Researcher: pull real-world data BEFORE codegen so the UI has
        #    facts to render instead of LLM hallucination.
        if not turn.cancelled:
            turn.status = "researching"
            try:
                await state.researcher.research(
                    turn,
                    directed.plan,
                    attached_files=attached,
                )
                await persistence.save_turn(turn)
            except Exception as exc:
                log.exception("researcher failed (non-fatal): %s", exc)
                turn.emit({"type": "research_failed", "message": str(exc)})

        # 5. Codegen
        turn.status = "generating"
        turn.emit({"type": "codegen_started"})
        if turn.cancelled:
            return

        async def _on_codegen_chunk(partial: str) -> None:
            # Stream the in-progress HTML to the host shell. The shell
            # feeds it into the iframe via srcDoc while status=generating,
            # so the user watches the document being drawn live.
            turn.emit({"type": "codegen_chunk", "html": partial, "bytes": len(partial)})

        html, usage = await state.codegen.generate(
            goal=turn.user_message,
            plan=directed.plan,
            files=attached,
            research=turn.state.get("research"),
            on_chunk=_on_codegen_chunk,
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

        async def _on_codegen_chunk(partial: str) -> None:
            turn.emit({"type": "codegen_chunk", "html": partial, "bytes": len(partial)})

        html, usage = await state.codegen.generate(
            goal=turn.user_message,
            plan=turn.plan,
            files=attached,
            refine_note=refine_note,
            previous_html=previous_html,
            research=turn.state.get("research"),
            on_chunk=_on_codegen_chunk,
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
