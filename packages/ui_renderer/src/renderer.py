"""UI Renderer - converts UIDocument to JSON-serializable dict."""

from datetime import date, datetime
from typing import Any
from packages.ui_dsl.src.schema import UIDocument, UIBlock, BlockType, ActionModel, ActionType


def _serialize_value(val: Any) -> Any:
    """Ensure a value is JSON-serializable."""
    if isinstance(val, (date, datetime)):
        return val.isoformat()
    if isinstance(val, set):
        return list(val)
    if isinstance(val, dict):
        return {k: _serialize_value(v) for k, v in val.items()}
    if isinstance(val, list):
        return [_serialize_value(item) for item in val]
    return val


def _action_to_dict(action: ActionModel) -> dict[str, Any]:
    """Convert an ActionModel to a JSON-serializable dict."""
    return {
        "id": action.id,
        "type": action.type.value,
        "label": action.label,
        "handler": action.handler,
        "params": _serialize_value(action.params),
        "disabled": action.disabled,
        "icon": action.icon,
    }


def _block_to_dict(block: UIBlock) -> dict[str, Any]:
    """Convert a UIBlock to a JSON-serializable dict."""
    return {
        "id": block.id,
        "type": block.type.value,
        "content": _serialize_value(block.content),
        "actions": [_action_to_dict(a) for a in block.actions],
        "metadata": _serialize_value(block.metadata),
    }


class UIDocumentRenderer:
    """Renders a UIDocument to a JSON-serializable dict."""

    BLOCK_TYPE_MAPPING = {
        BlockType.TEXT: "text",
        BlockType.STAT: "stat",
        BlockType.CARD: "card",
        BlockType.SECTION: "section",
        BlockType.LIST: "list",
        BlockType.TABLE: "table",
        BlockType.CHART: "chart",
        BlockType.FORM: "form",
        BlockType.SELECTOR: "selector",
        BlockType.TIMELINE: "timeline",
        BlockType.IMAGE: "image",
        BlockType.ACTION_BAR: "action_bar",
    }

    def render_document(self, uidocument: UIDocument) -> dict[str, Any]:
        """Render a UIDocument to a JSON-serializable dict.

        Args:
            uidocument: The UIDocument to render.

        Returns:
            A JSON-serializable dict containing all document information.
        """
        return {
            "version": uidocument.version,
            "id": uidocument.id,
            "title": uidocument.title,
            "blocks": [_block_to_dict(b) for b in uidocument.blocks],
            "metadata": _serialize_value(uidocument.metadata),
        }
