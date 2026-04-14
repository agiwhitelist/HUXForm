from .models import AgentState, Task
from .checkpoint import CheckpointManager
from .dependency import DependencyTracker
from .memory import MemoryBridge

class ActionLoop:
    def __init__(
        self,
        checkpoint_manager: CheckpointManager,
        dependency_tracker: DependencyTracker,
        memory_bridge: MemoryBridge,
    ):
        self.checkpoint_manager = checkpoint_manager
        self.dependency_tracker = dependency_tracker
        self.memory_bridge = memory_bridge

    async def step(
        self,
        state: AgentState,
        planner_fn,
        executor_fn,
        updater_fn,
    ) -> AgentState:
        checkpoint_id = await self.checkpoint_manager.checkpoint(state)
        plan = await planner_fn(state)
        result = await executor_fn(plan)
        state = await updater_fn(state, result)
        state["last_checkpoint"] = checkpoint_id
        state["state_version"] = state.get("state_version", 0) + 1
        state["loop_count"] = state.get("loop_count", 0) + 1
        await self.memory_bridge.sync_to_long_term(state)
        return state

    def is_terminal(self, state: AgentState) -> bool:
        return len(state.get("task_queue", [])) == 0 and state.get("loop_count", 0) >= 100
