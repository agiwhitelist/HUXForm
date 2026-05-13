"""Task state + event stream.

A Task is a single user intent end-to-end: planning, codegen, execution.
The generated UI subscribes to its event stream over SSE and pushes
actions back through the tool broker.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator


@dataclass
class TaskPlan:
    task_type: str
    presentation_mode: str
    visual_concept: str
    rationale: str
    steps: list[str]
    tool_hints: list[str]
    needs_user_input: bool


@dataclass
class Task:
    id: str
    goal: str
    created_at: float
    plan: TaskPlan | None = None
    html: str | None = None
    state: dict[str, Any] = field(default_factory=dict)
    status: str = "planning"  # planning | generating | running | awaiting_approval | done | failed
    final_result: Any = None
    error: str | None = None

    # event fan-out
    _queues: list[asyncio.Queue[dict[str, Any]]] = field(default_factory=list, repr=False)
    _history: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _pending_approvals: dict[str, asyncio.Future[bool]] = field(default_factory=dict, repr=False)

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=256)
        # replay history so a late subscriber catches up
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
        for q in list(self._queues):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass


class TaskRegistry:
    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}
        self._lock = asyncio.Lock()

    async def create(self, goal: str) -> Task:
        async with self._lock:
            task_id = uuid.uuid4().hex[:12]
            task = Task(id=task_id, goal=goal, created_at=time.time())
            self._tasks[task_id] = task
            return task

    def get(self, task_id: str) -> Task | None:
        return self._tasks.get(task_id)

    def require(self, task_id: str) -> Task:
        task = self.get(task_id)
        if task is None:
            raise KeyError(task_id)
        return task


async def stream_events(task: Task) -> AsyncIterator[dict[str, Any]]:
    q = task.subscribe()
    try:
        while True:
            try:
                ev = await asyncio.wait_for(q.get(), timeout=20.0)
            except asyncio.TimeoutError:
                # keep-alive comment frame for SSE
                yield {"type": "heartbeat"}
                continue
            yield ev
            if ev.get("type") in ("final_result", "failed"):
                # Give the client one tick to receive, then stop.
                await asyncio.sleep(0.05)
                return
    finally:
        task.unsubscribe(q)
