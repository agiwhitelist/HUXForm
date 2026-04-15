"""File-based session persistence for AGUI sessions."""

import json
from pathlib import Path
from typing import Any


class FilePersistence:
    """Manages session persistence using JSON files in .agui_sessions/ directory."""

    def __init__(self, base_dir: Path | None = None) -> None:
        if base_dir is None:
            base_dir = Path(__file__).parent.parent.parent / ".agui_sessions"
        self._base_dir = base_dir
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def _session_path(self, session_id: str) -> Path:
        """Get the file path for a session."""
        return self._base_dir / f"{session_id}.json"

    def save_session(self, session_id: str, data: dict[str, Any]) -> None:
        """Save a session to a JSON file."""
        path = self._session_path(session_id)
        path.write_text(json.dumps(data, indent=2))

    def load_session(self, session_id: str) -> dict[str, Any] | None:
        """Load a session from a JSON file. Returns None if not found."""
        path = self._session_path(session_id)
        if not path.exists():
            return None
        return json.loads(path.read_text())

    def load_all_sessions(self) -> dict[str, dict[str, Any]]:
        """Load all sessions from the sessions directory."""
        sessions = {}
        if not self._base_dir.exists():
            return sessions
        for path in self._base_dir.glob("*.json"):
            session_id = path.stem
            sessions[session_id] = json.loads(path.read_text())
        return sessions

    def delete_session(self, session_id: str) -> bool:
        """Delete a session file. Returns True if deleted, False if not found."""
        path = self._session_path(session_id)
        if path.exists():
            path.unlink()
            return True
        return False


# Global instance
persistence = FilePersistence()
