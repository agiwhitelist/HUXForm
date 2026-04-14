"""UI-DSL schema and types."""

from dataclasses import dataclass, field
from typing import Any
from enum import Enum


class BlockType(Enum):
    """Supported UI block types."""
    TEXT = "text"
    STAT = "stat"
    CARD = "card"
    SECTION = "section"
    LIST = "list"
    TABLE = "table"
    CHART = "chart"
    FORM = "form"
    SELECTOR = "selector"
    TIMELINE = "timeline"
    IMAGE = "image"
    ACTION_BAR = "action_bar"


class ActionType(Enum):
    """Action types for interactive elements."""
    BUTTON = "button"
    LINK = "link"
    SUBMIT = "submit"
    NAVIGATE = "navigate"


@dataclass
class ActionModel:
    """Action that can be triggered from a UI element."""
    id: str
    type: ActionType
    label: str
    handler: str | None = None  # Handler identifier
    params: dict[str, Any] = field(default_factory=dict)
    disabled: bool = False
    icon: str | None = None


@dataclass
class UIBlock:
    """A single UI block within a document."""
    id: str
    type: BlockType
    content: dict[str, Any]
    actions: list[ActionModel] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type.value,
            "content": self.content,
            "actions": [a.__dict__ for a in self.actions],
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UIBlock":
        actions = [ActionModel(**a) for a in data.get("actions", [])]
        return cls(
            id=data["id"],
            type=BlockType(data["type"]),
            content=data["content"],
            actions=actions,
            metadata=data.get("metadata", {}),
        )


@dataclass
class UIDocument:
    """UI document envelope containing blocks."""
    version: str = "1.0"
    id: str | None = None
    title: str | None = None
    blocks: list[UIBlock] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "id": self.id,
            "title": self.title,
            "blocks": [b.to_dict() for b in self.blocks],
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UIDocument":
        blocks = [UIBlock.from_dict(b) for b in data.get("blocks", [])]
        return cls(
            version=data.get("version", "1.0"),
            id=data.get("id"),
            title=data.get("title"),
            blocks=blocks,
            metadata=data.get("metadata", {}),
        )

    def add_block(self, block: UIBlock) -> None:
        """Add a block to the document."""
        self.blocks.append(block)

    def get_block(self, block_id: str) -> UIBlock | None:
        """Get a block by ID."""
        for block in self.blocks:
            if block.id == block_id:
                return block
        return None