"""UI generation from task results."""

from typing import Any

from packages.ui_dsl.src.schema import UIDocument, UIBlock, BlockType, ActionModel, ActionType


class UIGenerator:
    """Generates UI DSL documents from task results."""

    def __init__(self):
        pass

    async def generate(self, task_results: list[dict[str, Any]], context: dict[str, Any]) -> UIDocument:
        """Generate a UI document from task results."""
        doc = UIDocument(
            version="1.0",
            title=context.get("title", "AGUI Response"),
            blocks=[],
        )

        # Add status block showing task completion
        status_block = UIBlock(
            id="status-1",
            type=BlockType.SECTION,
            content={"title": "Task Results", "level": 2},
            actions=[],
        )
        doc.add_block(status_block)

        # Add result blocks
        for i, result in enumerate(task_results):
            result_block = UIBlock(
                id=f"result-{i}",
                type=BlockType.CARD,
                content={
                    "title": result.get("description", f"Task {i+1}"),
                    "description": result.get("status", "completed"),
                    "items": self._extract_items(result),
                },
                actions=[],
            )
            doc.add_block(result_block)

        # Add action bar for next steps
        action_bar = UIBlock(
            id="actions-1",
            type=BlockType.ACTION_BAR,
            content={},
            actions=[
                ActionModel(
                    id="new-task",
                    type=ActionType.BUTTON,
                    label="New Task",
                    handler="new_task",
                ),
                ActionModel(
                    id="view-history",
                    type=ActionType.BUTTON,
                    label="View History",
                    handler="view_history",
                ),
            ],
        )
        doc.add_block(action_bar)

        return doc

    def _extract_items(self, result: dict[str, Any]) -> list[dict[str, str]]:
        """Extract display items from result."""
        items = []
        for key, value in result.items():
            if key not in ["status", "description"]:
                items.append({"label": key, "value": str(value)})
        return items

    async def generate_error(self, error: str, context: dict[str, Any]) -> UIDocument:
        """Generate UI for error state."""
        doc = UIDocument(
            version="1.0",
            title="Error",
            blocks=[
                UIBlock(
                    id="error-1",
                    type=BlockType.TEXT,
                    content={
                        "text": f"An error occurred: {error}",
                        "format": "plain"
                    },
                    actions=[],
                ),
                UIBlock(
                    id="retry-actions",
                    type=BlockType.ACTION_BAR,
                    content={},
                    actions=[
                        ActionModel(
                            id="retry",
                            type=ActionType.BUTTON,
                            label="Retry",
                            handler="retry",
                        ),
                    ],
                ),
            ],
        )
        return doc