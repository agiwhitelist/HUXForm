"""Tool registry with lifecycle management."""

from typing import Any, Callable
import asyncio

from .states import ToolDefinition, ToolState
from .discovery import (
    DiscoverySource,
    MCPDiscoverySource,
    WebSearchDiscoverySource,
    CodeGenDiscoverySource,
)


class ToolRegistry:
    """Central registry for tool management and discovery."""

    def __init__(self):
        self._tools: dict[str, ToolDefinition] = {}
        self._handlers: dict[str, Callable] = {}
        self._discovery_sources: list[DiscoverySource] = [
            MCPDiscoverySource(),
            WebSearchDiscoverySource(),
            CodeGenDiscoverySource(),
        ]

    def register_source(self, source: DiscoverySource) -> None:
        """Add a discovery source."""
        self._discovery_sources.append(source)

    async def discover_tools(self, source: str | None = None) -> list[ToolDefinition]:
        """Discover tools from configured sources."""
        discovered = []
        for ds in self._discovery_sources:
            if source is None or ds.supports(source):
                tools = await ds.discover()
                for tool in tools:
                    self._tools[tool.name] = tool
                    tool.transition_to(ToolState.DISCOVERED)
                    discovered.append(tool)
        return discovered

    def register_tool(
        self,
        name: str,
        description: str,
        schema: dict[str, Any],
        handler: Callable,
        source: str = "manual",
        metadata: dict[str, Any] | None = None
    ) -> ToolDefinition:
        """Manually register a tool."""
        tool = ToolDefinition(
            name=name,
            description=description,
            source=source,
            schema=schema,
            handler=handler,
            metadata=metadata or {},
        )
        tool.transition_to(ToolState.REGISTERED)
        tool.transition_to(ToolState.AVAILABLE)
        self._tools[name] = tool
        self._handlers[name] = handler
        return tool

    async def execute_tool(
        self,
        name: str,
        parameters: dict[str, Any]
    ) -> dict[str, Any]:
        """Execute a tool by name with given parameters."""
        if name not in self._tools:
            raise ValueError(f"Tool '{name}' not found in registry")

        tool = self._tools[name]
        if tool.state != ToolState.AVAILABLE:
            raise RuntimeError(f"Tool '{name}' is not available (state: {tool.state.value})")

        tool.transition_to(ToolState.EXECUTING)

        try:
            handler = self._handlers.get(name)
            if not handler:
                raise RuntimeError(f"No handler registered for tool '{name}'")

            # Handle async and sync handlers
            if asyncio.iscoroutinefunction(handler):
                result = await handler(**parameters)
            else:
                result = handler(**parameters)

            tool.transition_to(ToolState.SUCCESS)
            return {"success": True, "result": result}
        except Exception as e:
            tool.transition_to(ToolState.FAILED)
            return {"success": False, "error": str(e)}

    def get_tool(self, name: str) -> ToolDefinition | None:
        """Get a tool definition by name."""
        return self._tools.get(name)

    def get_tools_by_state(self, state: ToolState) -> list[ToolDefinition]:
        """Get all tools in a specific state."""
        return [t for t in self._tools.values() if t.state == state]

    def get_tools_by_source(self, source: str) -> list[ToolDefinition]:
        """Get all tools from a specific source."""
        return [t for t in self._tools.values() if t.source == source]

    def list_tools(self) -> list[dict[str, Any]]:
        """List all registered tools."""
        return [t.to_dict() for t in self._tools.values()]