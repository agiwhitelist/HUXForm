"""SQLite persistence for threads, turns, events and files.

Designed as a Registry listener: when the in-memory Registry creates a
thread / turn / file, we mirror it to disk. Events are written
incrementally by attaching to each turn's stream.

Hydration: on boot we replay threads + turns. Active turns rehydrate
their event history; finished turns load with their terminal state.
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Optional

from .tasks import FileRecord, Registry, TaskPlan, Thread, Turn, VisualBrief


SCHEMA = """
CREATE TABLE IF NOT EXISTS threads (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS turns (
  id TEXT PRIMARY KEY,
  thread_id TEXT NOT NULL,
  parent_turn_id TEXT,
  user_message TEXT NOT NULL,
  created_at REAL NOT NULL,
  status TEXT NOT NULL,
  plan_json TEXT,
  answer_text TEXT,
  html TEXT,
  state_json TEXT NOT NULL DEFAULT '{}',
  final_result_json TEXT,
  error TEXT,
  usage_json TEXT NOT NULL DEFAULT '{}',
  file_ids_json TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS turns_by_thread ON turns(thread_id, created_at);
CREATE TABLE IF NOT EXISTS events (
  turn_id TEXT NOT NULL,
  seq INTEGER NOT NULL,
  ts REAL NOT NULL,
  payload TEXT NOT NULL,
  PRIMARY KEY (turn_id, seq)
);
CREATE TABLE IF NOT EXISTS files (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  mime TEXT NOT NULL,
  size INTEGER NOT NULL,
  path TEXT NOT NULL,
  created_at REAL NOT NULL
);
"""


class Persistence:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False, isolation_level=None)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA synchronous=NORMAL;")
        self._conn.executescript(SCHEMA)
        self._lock = asyncio.Lock()
        self._event_seq: dict[str, int] = {}

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass

    # --- Registry listener hooks -------------------------------------------

    async def on_thread_created(self, thread: Thread) -> None:
        async with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO threads(id, title, created_at) VALUES(?, ?, ?)",
                (thread.id, thread.title, thread.created_at),
            )

    async def on_thread_updated(self, thread: Thread) -> None:
        async with self._lock:
            self._conn.execute(
                "UPDATE threads SET title=? WHERE id=?",
                (thread.title, thread.id),
            )

    async def on_turn_created(self, turn: Turn) -> None:
        async with self._lock:
            self._conn.execute(
                """INSERT OR REPLACE INTO turns(
                   id, thread_id, parent_turn_id, user_message, created_at, status,
                   plan_json, answer_text, html, state_json, final_result_json, error,
                   usage_json, file_ids_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    turn.id,
                    turn.thread_id,
                    turn.parent_turn_id,
                    turn.user_message,
                    turn.created_at,
                    turn.status,
                    None,
                    None,
                    None,
                    "{}",
                    None,
                    None,
                    "{}",
                    json.dumps(turn.file_ids),
                ),
            )

    async def on_file_added(self, rec: FileRecord) -> None:
        async with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO files(id, name, mime, size, path, created_at) VALUES(?,?,?,?,?,?)",
                (rec.id, rec.name, rec.mime, rec.size, rec.path, rec.created_at),
            )

    # --- Direct persistence calls (called from the pipeline) ---------------

    async def save_turn(self, turn: Turn) -> None:
        plan_json = json.dumps(turn.plan.to_dict()) if turn.plan else None
        async with self._lock:
            self._conn.execute(
                """UPDATE turns SET
                   status=?, plan_json=?, answer_text=?, html=?, state_json=?,
                   final_result_json=?, error=?, usage_json=?
                   WHERE id=?""",
                (
                    turn.status,
                    plan_json,
                    turn.answer_text,
                    turn.html,
                    json.dumps(turn.state),
                    json.dumps(turn.final_result) if turn.final_result is not None else None,
                    turn.error,
                    json.dumps(turn.usage),
                    turn.id,
                ),
            )

    async def append_event(self, turn_id: str, event: dict[str, Any]) -> None:
        seq = self._event_seq.get(turn_id, 0) + 1
        self._event_seq[turn_id] = seq
        async with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO events(turn_id, seq, ts, payload) VALUES(?,?,?,?)",
                    (turn_id, seq, event.get("ts") or time.time(), json.dumps(event, default=str)),
                )
            except sqlite3.IntegrityError:
                # rare race; skip
                pass

    # --- Hydration ---------------------------------------------------------

    def hydrate(self, registry: Registry) -> None:
        cur = self._conn.execute("SELECT id, title, created_at FROM threads ORDER BY created_at")
        for tid, title, created in cur.fetchall():
            registry.threads[tid] = Thread(id=tid, title=title, created_at=created)
        cur = self._conn.execute(
            """SELECT id, thread_id, parent_turn_id, user_message, created_at, status,
                      plan_json, answer_text, html, state_json, final_result_json, error,
                      usage_json, file_ids_json
               FROM turns ORDER BY created_at"""
        )
        for row in cur.fetchall():
            (tid, thread_id, parent_id, msg, created, status,
             plan_json, answer_text, html, state_json, final_json, error,
             usage_json, file_ids_json) = row
            turn = Turn(
                id=tid,
                thread_id=thread_id,
                user_message=msg,
                created_at=created,
                parent_turn_id=parent_id,
                file_ids=json.loads(file_ids_json or "[]"),
            )
            turn.status = status if status in {"done", "failed", "cancelled"} else "cancelled"
            turn.state = json.loads(state_json or "{}")
            turn.answer_text = answer_text
            turn.html = html
            turn.error = error
            turn.usage = json.loads(usage_json or "{}")
            if final_json is not None:
                try:
                    turn.final_result = json.loads(final_json)
                except json.JSONDecodeError:
                    turn.final_result = final_json
            if plan_json:
                try:
                    pd = json.loads(plan_json)
                    vb = pd.get("visual_brief") or None
                    brief = None
                    if vb:
                        brief = VisualBrief(
                            metaphor=vb.get("metaphor", ""),
                            palette=vb.get("palette", {}) or {},
                            typography=vb.get("typography", {}) or {},
                            layout=vb.get("layout", ""),
                            interaction=vb.get("interaction", ""),
                            motion=vb.get("motion", ""),
                            microcopy_tone=vb.get("microcopy_tone", ""),
                            banned_patterns=list(vb.get("banned_patterns") or []),
                            inspirations=list(vb.get("inspirations") or []),
                        )
                    turn.plan = TaskPlan(
                        task_type=pd.get("task_type", "general"),
                        presentation_mode=pd.get("presentation_mode", "status_view"),
                        visual_concept=pd.get("visual_concept", ""),
                        rationale=pd.get("rationale", ""),
                        steps=list(pd.get("steps") or []),
                        tool_hints=list(pd.get("tool_hints") or []),
                        needs_user_input=bool(pd.get("needs_user_input", False)),
                        visual_brief=brief,
                    )
                except json.JSONDecodeError:
                    pass
            registry.turns[tid] = turn
            thread = registry.threads.get(thread_id)
            if thread:
                thread.turn_ids.append(tid)

        cur = self._conn.execute("SELECT id, name, mime, size, path, created_at FROM files")
        for fid, name, mime, size, path, created in cur.fetchall():
            registry.files[fid] = FileRecord(
                id=fid, name=name, mime=mime, size=size, path=path, created_at=created,
            )

    def load_events(self, turn_id: str, limit: int = 1000) -> list[dict[str, Any]]:
        cur = self._conn.execute(
            "SELECT payload FROM events WHERE turn_id=? ORDER BY seq DESC LIMIT ?",
            (turn_id, limit),
        )
        rows = [json.loads(p) for (p,) in cur.fetchall()]
        rows.reverse()
        return rows


class EventPersistor:
    """Per-turn task that listens to a turn's stream and writes events to disk."""

    def __init__(self, persistence: Persistence) -> None:
        self.p = persistence

    def attach(self, turn: Turn) -> asyncio.Task:
        return asyncio.create_task(self._run(turn))

    async def _run(self, turn: Turn) -> None:
        q = turn.subscribe()
        try:
            while True:
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=60.0)
                except asyncio.TimeoutError:
                    if turn.status in {"done", "failed", "cancelled"}:
                        return
                    continue
                if ev.get("type") == "heartbeat":
                    continue
                await self.p.append_event(turn.id, ev)
                if ev.get("type") in {"final_result", "failed", "cancelled"}:
                    await self.p.save_turn(turn)
                    return
        finally:
            turn.unsubscribe(q)
