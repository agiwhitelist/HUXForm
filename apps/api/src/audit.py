"""Simple append-only audit log for tool calls and approvals.

Mirrors what's in events but in a stable, queryable form. Useful both
for debugging and for the human Inspector panel.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from pathlib import Path
from typing import Any

AUDIT_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL NOT NULL,
  turn_id TEXT,
  kind TEXT NOT NULL,
  data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS audit_by_turn ON audit(turn_id, ts);
"""


class Audit:
    def __init__(self, db_path: str | Path) -> None:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False, isolation_level=None)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.executescript(AUDIT_SCHEMA)
        self._lock = asyncio.Lock()

    async def record(self, *, kind: str, turn_id: str | None, data: dict[str, Any]) -> None:
        async with self._lock:
            self._conn.execute(
                "INSERT INTO audit(ts, turn_id, kind, data) VALUES(?,?,?,?)",
                (time.time(), turn_id, kind, json.dumps(data, default=str)),
            )

    def tail(self, *, turn_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        if turn_id:
            cur = self._conn.execute(
                "SELECT ts, kind, data FROM audit WHERE turn_id=? ORDER BY id DESC LIMIT ?",
                (turn_id, limit),
            )
        else:
            cur = self._conn.execute(
                "SELECT ts, kind, data FROM audit ORDER BY id DESC LIMIT ?",
                (limit,),
            )
        out = []
        for ts, kind, data in cur.fetchall():
            try:
                payload = json.loads(data)
            except json.JSONDecodeError:
                payload = {"raw": data}
            out.append({"ts": ts, "kind": kind, "data": payload})
        return out

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass
