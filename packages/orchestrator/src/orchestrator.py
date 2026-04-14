"""Main Orchestrator class that ties all components together."""

from typing import Any

from .intent import IntentClassifier, IntentType
from .planner import Planner, PlannedTask
from .ui_generator import UIGenerator


class Orchestrator:
    """Core orchestrator that coordinates all AGUI components."""

    def __init__(
        self,
        llm_router=None,
        tool_registry=None,
        state_store=None,
    ):
        self.llm_router = llm_router
        self.tool_registry = tool_registry
        self.state_store = state_store
        self.intent_classifier = IntentClassifier(llm_router)
        self.planner = Planner(tool_registry)
        self.ui_generator = UIGenerator()

    async def process(self, user_input: str, session_id: str | None = None, context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Process user input and return response with UI."""
        context = context or {}

        # Step 1: Classify intent
        intent = await self.intent_classifier.classify(user_input)

        # Step 2: Create and execute plan
        tasks = await self.planner.create_plan(intent, context)
        completed_tasks = await self.planner.execute_plan(tasks)

        # Step 3: Generate UI from results
        task_results = [
            {
                "id": t.id,
                "description": t.description,
                "status": t.status.value,
                "result": t.result,
                "error": t.error,
            }
            for t in completed_tasks
        ]

        ui_doc = await self.ui_generator.generate(task_results, {**context, "title": "Response"})

        return {
            "intent": {
                "type": intent.type.value,
                "confidence": intent.confidence,
                "raw_input": intent.raw_input,
            },
            "tasks": task_results,
            "ui_document": ui_doc.to_dict(),
            "session_id": session_id or "default",
        }

    async def handle_action(self, action_id: str, params: dict[str, Any], session_id: str | None = None) -> dict[str, Any]:
        """Handle a UI action."""
        # Process action through tool registry
        if self.tool_registry:
            result = await self.tool_registry.execute_tool(action_id, params)
            return result

        return {"success": False, "error": "No tool registry configured"}