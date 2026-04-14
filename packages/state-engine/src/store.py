import json
from typing import Any
from .models import AgentState

class StateStore:
    async def save(self, state: AgentState, checkpoint_id: str | None = None) -> str:
        checkpoint_id = checkpoint_id or f"cp_{state.get('state_version', 0)}"
        return checkpoint_id

    async def load(self, checkpoint_id: str) -> AgentState:
        return AgentState()

    async def list_checkpoints(self, session_id: str) -> list[str]:
        return []
