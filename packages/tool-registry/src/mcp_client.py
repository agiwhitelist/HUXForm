import json
import subprocess
from typing import Any
from .models import Tool
from .lifecycle import ToolState

class MCPClient:
    def __init__(self, server_command: list[str]):
        self.server_command = server_command
        self._process: subprocess.Popen | None = None
        self._capabilities: dict[str, Any] = {}

    async def connect(self) -> None:
        self._process = subprocess.Popen(
            self.server_command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        init_request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "agui", "version": "0.1.0"}
            }
        }
        self._process.stdin.write(json.dumps(init_request).encode() + b"\n")
        self._process.stdin.flush()

    async def list_tools(self) -> list[Tool]:
        if not self._process:
            raise RuntimeError("Not connected")
        request = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
        self._process.stdin.write(json.dumps(request).encode() + b"\n")
        self._process.stdin.flush()
        line = self._process.stdout.readline()
        response = json.loads(line)
        tools = []
        for tool_def in response.get("result", {}).get("tools", []):
            tools.append(Tool(
                id=f"mcp-{tool_def['name']}",
                name=tool_def["name"],
                description=tool_def.get("description", ""),
                provider="mcp",
                input_schema=tool_def.get("inputSchema", {}),
                metadata={"server": "mcp", "original_def": tool_def}
            ))
        return tools

    async def call_tool(self, tool_name: str, args: dict[str, Any]) -> Any:
        if not self._process:
            raise RuntimeError("Not connected")
        request = {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": tool_name, "arguments": args}}
        self._process.stdin.write(json.dumps(request).encode() + b"\n")
        self._process.stdin.flush()
        line = self._process.stdout.readline()
        response = json.loads(line)
        return response.get("result")

    def disconnect(self) -> None:
        if self._process:
            self._process.terminate()
            self._process = None
