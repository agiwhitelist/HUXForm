from typing import Any
from .models import Tool

class CodeGenerator:
    def generate_tool_from_description(self, description: str, requirements: dict[str, Any]) -> str:
        tool_code = f"""
def generated_tool(args):
    # Auto-generated from: {description}
    return {{"result": "generated"}}
"""
        return tool_code

    def create_tool(self, name: str, description: str, code: str) -> Tool:
        return Tool(
            id=f"generated-{name}",
            name=name,
            description=description,
            provider="generated",
            input_schema={"type": "object", "properties": {}, "required": []},
            metadata={"code": code, "generated_at": "now"}
        )
