from dataclasses import dataclass, field
from typing import TypedDict, Annotated, Any
from operator import add

@dataclass
class Message:
    id: str
    role: str  # 'user' | 'assistant' | 'system' | 'tool'
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass
class Task:
    id: str
    description: str
    status: str = "pending"  # 'pending' | 'in_progress' | 'completed' | 'failed'
    result: Any | None = None

@dataclass
class TaskResult:
    task_id: str
    success: bool
    result: Any | None = None
    error: str | None = None

@dataclass
class Observation:
    key: str
    value: Any
    timestamp: int

# LangGraph-style TypedDict with Annotated for immutable updates
class AgentState(TypedDict):
    messages: Annotated[list[Message], add]
    current_task: Task | None
    task_queue: list[Task]
    completed_tasks: list[TaskResult]
    observations: dict[str, Observation]
    pending_actions: list[str]
    memory_snapshot: str | None
    loop_count: int
    last_checkpoint: str | None
    state_version: int
