"""Task planning for orchestrator."""

from dataclasses import dataclass, field
from typing import Any
from enum import Enum


class TaskStatus(Enum):
    """Status of a planned task."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class PlannedTask:
    """A task to be executed as part of a plan."""
    id: str
    description: str
    tool_name: str | None = None
    params: dict[str, Any] = field(default_factory=dict)
    status: TaskStatus = TaskStatus.PENDING
    result: Any = None
    error: str | None = None


class Planner:
    """Creates and manages execution plans from intent."""

    def __init__(self, tool_registry=None):
        self.tool_registry = tool_registry

    async def create_plan(self, intent: Any, context: dict[str, Any]) -> list[PlannedTask]:
        """Create a plan of tasks to execute for the given intent."""
        tasks = []

        # Create task based on intent type
        if intent.type.value == "query":
            # Query intent - use LLM to generate response
            tasks.append(PlannedTask(
                id="query-1",
                description="Process query via LLM",
                tool_name="llm",
                params={"prompt": intent.raw_input}
            ))
        elif intent.type.value == "action":
            # Action intent - execute tool
            tasks.append(PlannedTask(
                id="action-1",
                description="Execute action",
                tool_name="execute",
                params={"action": intent.raw_input}
            ))
        elif intent.type.value == "create":
            # Create intent - generate and register tool
            tasks.append(PlannedTask(
                id="create-1",
                description="Generate new tool",
                tool_name="code-gen",
                params={"intent": intent.raw_input}
            ))
        elif intent.type.value == "search":
            # Search intent - discover and filter tools
            tasks.append(PlannedTask(
                id="search-1",
                description="Search for tools",
                tool_name="discovery",
                params={"query": intent.raw_input}
            ))
        else:
            # Unknown intent - return help
            tasks.append(PlannedTask(
                id="help-1",
                description="Show available commands",
                tool_name="help",
                params={}
            ))

        return tasks

    async def execute_plan(self, tasks: list[PlannedTask]) -> list[PlannedTask]:
        """Execute a plan of tasks."""
        for task in tasks:
            task.status = TaskStatus.RUNNING
            try:
                # Execute task based on tool
                if task.tool_name == "llm":
                    task.result = {"status": "processed"}
                elif task.tool_name == "execute":
                    task.result = {"status": "executed"}
                elif task.tool_name == "code-gen":
                    task.result = {"status": "generated"}
                elif task.tool_name == "discovery":
                    task.result = {"status": "searched"}
                elif task.tool_name == "help":
                    task.result = {"status": "help_shown"}
                else:
                    task.result = {"status": "unknown_tool"}

                task.status = TaskStatus.COMPLETED
            except Exception as e:
                task.status = TaskStatus.FAILED
                task.error = str(e)

        return tasks