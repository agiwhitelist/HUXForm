from dataclasses import dataclass, field
from typing import Any, Callable
from .lifecycle import ToolState

@dataclass
class Tool:
    id: str
    name: str
    description: str
    provider: str  # 'mcp' | 'web' | 'generated' | 'builtin'
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] | None = None
    handler: Callable[..., Any] | None = None
    state: ToolState = ToolState.DISCOVERED
    metadata: dict[str, Any] = field(default_factory=dict)
    error_count: int = 0

    def validate_input(self, args: dict[str, Any]) -> bool:
        required = self.input_schema.get("required", [])
        for req in required:
            if req not in args:
                raise ValueError(f"Missing required argument: {req}")
        return True
