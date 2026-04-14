"""Tool lifecycle and state management."""

from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


class ToolState(Enum):
    """Tool lifecycle states."""
    DISCOVERED = "discovered"
    REGISTERED = "registered"
    AVAILABLE = "available"
    EXECUTING = "executing"
    FAILED = "failed"
    SUCCESS = "success"


@dataclass
class ToolDefinition:
    """Definition of a discoverable tool."""
    name: str
    description: str
    source: str  # e.g., "mcp", "web-search", "code-gen"
    schema: dict[str, Any]
    handler: Any = None
    state: ToolState = ToolState.DISCOVERED
    metadata: dict[str, Any] = field(default_factory=dict)
    discovered_at: datetime = field(default_factory=datetime.now)
    registered_at: datetime | None = None

    def transition_to(self, new_state: ToolState) -> None:
        """Transition tool to a new state."""
        self.state = new_state
        if new_state == ToolState.REGISTERED:
            self.registered_at = datetime.now()

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "name": self.name,
            "description": self.description,
            "source": self.source,
            "schema": self.schema,
            "state": self.state.value,
            "metadata": self.metadata,
            "discovered_at": self.discovered_at.isoformat(),
            "registered_at": self.registered_at.isoformat() if self.registered_at else None,
        }