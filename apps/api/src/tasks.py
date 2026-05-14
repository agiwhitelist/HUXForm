"""Domain model: Threads, Turns, files, plans, event streams.

A *Thread* is the persistent conversation. Each user message creates a
*Turn*. A Turn carries its own plan, optional generated UI, mutable
task state, event history, and references to attached files. Turns within
a thread share context — refining a turn produces a follow-up turn linked
by `parent_turn_id`.

Events are fanned out via per-subscriber asyncio queues, with full replay
for late subscribers (so the iframe can drop and reconnect freely).
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional


# ---------------------------------------------------------------------------
# Plans / visual briefs
# ---------------------------------------------------------------------------


@dataclass
class VisualBrief:
    metaphor: str
    palette: dict[str, str]
    typography: dict[str, str]
    layout: str
    interaction: str
    motion: str
    microcopy_tone: str
    banned_patterns: list[str]
    inspirations: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "metaphor": self.metaphor,
            "palette": self.palette,
            "typography": self.typography,
            "layout": self.layout,
            "interaction": self.interaction,
            "motion": self.motion,
            "microcopy_tone": self.microcopy_tone,
            "banned_patterns": self.banned_patterns,
            "inspirations": self.inspirations,
        }


@dataclass
class TaskPlan:
    task_type: str
    presentation_mode: str
    visual_concept: str
    rationale: str
    steps: list[str]
    tool_hints: list[str]
    needs_user_input: bool
    visual_brief: VisualBrief | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_type": self.task_type,
            "presentation_mode": self.presentation_mode,
            "visual_concept": self.visual_concept,
            "rationale": self.rationale,
            "steps": self.steps,
            "tool_hints": self.tool_hints,
            "needs_user_input": self.needs_user_input,
            "visual_brief": self.visual_brief.to_dict() if self.visual_brief else None,
        }


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------


@dataclass
class FileRecord:
    id: str
    name: str
    mime: str
    size: int
    path: str  # filesystem path on the server
    created_at: float

    def to_public(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "mime": self.mime, "size": self.size}


# ---------------------------------------------------------------------------
# Turn (formerly "Task")
# ---------------------------------------------------------------------------


@dataclass
class Turn:
    id: str
    thread_id: str
    user_message: str
    created_at: float
    parent_turn_id: str | None = None
    file_ids: list[str] = field(default_factory=list)

    plan: TaskPlan | None = None
    answer_text: str | None = None  # answer_only short-circuit
    html: str | None = None
    state: dict[str, Any] = field(default_factory=dict)
    final_result: Any = None
    error: str | None = None

    # Lifecycle:
    #   created → planning → awaiting_steer → generating → running →
    #     [awaiting_approval] → done | failed | cancelled
    status: str = "created"
    auto_proceed: bool = True
    cancelled: bool = False
    usage: dict[str, int] = field(default_factory=lambda: {"input_tokens": 0, "output_tokens": 0})

    # Internal coordination
    _steer_event: asyncio.Event = field(default_factory=asyncio.Event, repr=False)
    _cancel_event: asyncio.Event = field(default_factory=asyncio.Event, repr=False)
    _queues: list[asyncio.Queue[dict[str, Any]]] = field(default_factory=list, repr=False)
    _history: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _pending_approvals: dict[str, asyncio.Future] = field(default_factory=dict, repr=False)

    # Subscriber pattern -----------------------------------------------------
    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=512)
        for ev in self._history:
            try:
                q.put_nowait(ev)
            except asyncio.QueueFull:
                break
        self._queues.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[dict[str, Any]]) -> None:
        try:
            self._queues.remove(q)
        except ValueError:
            pass

    def emit(self, event: dict[str, Any]) -> None:
        event = {**event, "ts": time.time()}
        self._history.append(event)
        # cap history to avoid unbounded memory in long-running turns
        if len(self._history) > 2000:
            self._history = self._history[-1500:]
        for q in list(self._queues):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass

    # Steering / cancel ------------------------------------------------------
    def proceed(self) -> None:
        self._steer_event.set()

    def cancel(self) -> None:
        self.cancelled = True
        self._cancel_event.set()
        self._steer_event.set()
        # release any pending approvals
        for fut in list(self._pending_approvals.values()):
            if not fut.done():
                fut.set_result(False)
        self.status = "cancelled"
        self.emit({"type": "cancelled"})

    async def wait_for_steer(self, timeout: float | None) -> bool:
        """Returns True if proceed was signaled, False on timeout/cancel."""
        if self._steer_event.is_set():
            return not self.cancelled
        try:
            await asyncio.wait_for(self._steer_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            return False
        return not self.cancelled

    # Snapshot for API -------------------------------------------------------
    def to_snapshot(self, files: list[dict] | None = None) -> dict[str, Any]:
        return {
            "id": self.id,
            "thread_id": self.thread_id,
            "parent_turn_id": self.parent_turn_id,
            "user_message": self.user_message,
            "created_at": self.created_at,
            "status": self.status,
            "plan": self.plan.to_dict() if self.plan else None,
            "answer_text": self.answer_text,
            "state": self.state,
            "final_result": self.final_result,
            "error": self.error,
            "has_ui": self.html is not None,
            "files": files or [],
            "usage": self.usage,
        }


# ---------------------------------------------------------------------------
# Thread + registries
# ---------------------------------------------------------------------------


@dataclass
class Thread:
    id: str
    title: str
    created_at: float
    turn_ids: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Mission — multi-turn agentic execution toward one user goal
# ---------------------------------------------------------------------------


@dataclass
class MissionStep:
    title: str
    detail: str = ""
    turn_id: str | None = None
    status: str = "pending"  # pending | running | done | failed | timeout | skipped

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "detail": self.detail,
            "turn_id": self.turn_id,
            "status": self.status,
        }


@dataclass
class Mission:
    id: str
    thread_id: str
    goal: str
    created_at: float
    steps: list[MissionStep] = field(default_factory=list)
    current_step: int = 0
    # planning | running | done | failed | cancelled
    status: str = "planning"
    error: str | None = None
    cancelled: bool = False

    _queues: list[asyncio.Queue[dict[str, Any]]] = field(default_factory=list, repr=False)
    _history: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def emit(self, event: dict[str, Any]) -> None:
        event = {**event, "mission_id": self.id, "ts": time.time()}
        self._history.append(event)
        if len(self._history) > 500:
            self._history = self._history[-400:]
        for q in list(self._queues):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=256)
        for ev in self._history:
            try:
                q.put_nowait(ev)
            except asyncio.QueueFull:
                break
        self._queues.append(q)
        return q

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "thread_id": self.thread_id,
            "goal": self.goal,
            "created_at": self.created_at,
            "status": self.status,
            "error": self.error,
            "current_step": self.current_step,
            "steps": [s.to_dict() for s in self.steps],
        }


class Registry:
    """In-memory registry. PersistenceAdapter optionally hydrates/persists it."""

    def __init__(self) -> None:
        self.threads: dict[str, Thread] = {}
        self.turns: dict[str, Turn] = {}
        self.files: dict[str, FileRecord] = {}
        self.missions: dict[str, Mission] = {}
        self._lock = asyncio.Lock()
        self._listeners: list[Any] = []  # persistence adapters

    def add_listener(self, listener: Any) -> None:
        self._listeners.append(listener)

    async def _notify(self, kind: str, *args: Any) -> None:
        for L in self._listeners:
            handler = getattr(L, f"on_{kind}", None)
            if handler is None:
                continue
            res = handler(*args)
            if asyncio.iscoroutine(res):
                await res

    # Threads ----------------------------------------------------------------
    async def create_thread(self, title: str) -> Thread:
        async with self._lock:
            tid = uuid.uuid4().hex[:10]
            thread = Thread(id=tid, title=title, created_at=time.time())
            self.threads[tid] = thread
            await self._notify("thread_created", thread)
            return thread

    def get_thread(self, tid: str) -> Thread | None:
        return self.threads.get(tid)

    def list_threads(self) -> list[Thread]:
        return sorted(self.threads.values(), key=lambda t: t.created_at, reverse=True)

    async def update_thread_title(self, tid: str, title: str) -> None:
        thread = self.threads.get(tid)
        if not thread:
            return
        thread.title = title
        await self._notify("thread_updated", thread)

    # Turns ------------------------------------------------------------------
    async def create_turn(
        self,
        *,
        thread_id: str,
        user_message: str,
        parent_turn_id: str | None = None,
        file_ids: list[str] | None = None,
    ) -> Turn:
        async with self._lock:
            tid = uuid.uuid4().hex[:12]
            turn = Turn(
                id=tid,
                thread_id=thread_id,
                user_message=user_message,
                created_at=time.time(),
                parent_turn_id=parent_turn_id,
                file_ids=list(file_ids or []),
            )
            self.turns[tid] = turn
            thread = self.threads.get(thread_id)
            if thread:
                thread.turn_ids.append(tid)
            await self._notify("turn_created", turn)
            return turn

    def get_turn(self, tid: str) -> Turn | None:
        return self.turns.get(tid)

    def list_thread_turns(self, thread_id: str) -> list[Turn]:
        thread = self.threads.get(thread_id)
        if not thread:
            return []
        return [self.turns[i] for i in thread.turn_ids if i in self.turns]

    # Missions ---------------------------------------------------------------
    async def create_mission(self, *, thread_id: str, goal: str) -> Mission:
        async with self._lock:
            mid = uuid.uuid4().hex[:10]
            mission = Mission(id=mid, thread_id=thread_id, goal=goal, created_at=time.time())
            self.missions[mid] = mission
            return mission

    def get_mission(self, mid: str) -> Mission | None:
        return self.missions.get(mid)

    def list_thread_missions(self, thread_id: str) -> list[Mission]:
        return [m for m in self.missions.values() if m.thread_id == thread_id]

    # Files ------------------------------------------------------------------
    async def add_file(self, rec: FileRecord) -> None:
        async with self._lock:
            self.files[rec.id] = rec
            await self._notify("file_added", rec)

    def get_file(self, fid: str) -> FileRecord | None:
        return self.files.get(fid)


# ---------------------------------------------------------------------------
# SSE generator
# ---------------------------------------------------------------------------


async def stream_events(turn: Turn) -> AsyncIterator[dict[str, Any]]:
    q = turn.subscribe()
    try:
        terminal = {"final_result", "failed", "cancelled"}
        # If turn already finished, replay then end after a short grace
        already_done = turn.status in {"done", "failed", "cancelled"}
        while True:
            try:
                ev = await asyncio.wait_for(q.get(), timeout=20.0)
            except asyncio.TimeoutError:
                if already_done:
                    return
                yield {"type": "heartbeat", "ts": time.time()}
                continue
            yield ev
            if ev.get("type") in terminal:
                await asyncio.sleep(0.05)
                return
    finally:
        turn.unsubscribe(q)
