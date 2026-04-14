import httpx
from typing import Any
from .models import Tool

class WebDiscovery:
    async def search_api_docs(self, query: str) -> list[dict[str, Any]]:
        async with httpx.AsyncClient() as client:
            return []

    async def parse_openapi_spec(self, spec_url: str) -> list[Tool]:
        async with httpx.AsyncClient() as client:
            response = await client.get(spec_url)
            spec = response.json()
        tools = []
        for path, methods in spec.get("paths", {}).items():
            for method, operation in methods.items():
                if method.upper() in ["GET", "POST", "PUT", "DELETE"]:
                    tool_name = f"{method}_{path.replace('/', '_')}"
                    tools.append(Tool(
                        id=f"openapi-{tool_name}",
                        name=tool_name,
                        description=operation.get("summary", ""),
                        provider="web",
                        input_schema=operation.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema", {}),
                        metadata={"spec_url": spec_url, "path": path, "method": method}
                    ))
        return tools
