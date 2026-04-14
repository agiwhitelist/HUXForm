from enum import Enum
from .store import StateStore
from .models import AgentState

class CheckpointMode(Enum):
    EXIT = "exit"
    ASYNC = "async"
    SYNC = "sync"

class CheckpointManager:
    def __init__(self, store: StateStore, mode: CheckpointMode = CheckpointMode.SYNC):
        self.store = store
        self.mode = mode

    async def checkpoint(self, state: AgentState, checkpoint_id: str | None = None) -> str:
        if self.mode == CheckpointMode.EXIT:
            return checkpoint_id or "exit"
        return await self.store.save(state, checkpoint_id)

    async def restore(self, checkpoint_id: str) -> AgentState:
        return await self.store.load(checkpoint_id)
