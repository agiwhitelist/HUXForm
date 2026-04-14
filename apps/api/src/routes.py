"""API routes for chat, actions, sessions, and UI schema."""

from fastapi import APIRouter, HTTPException
from typing import Any

from .models import (
    ChatRequest,
    ChatResponse,
    ActionRequest,
    ActionResponse,
    SessionResponse,
    UISchemaResponse,
    Message,
)

router = APIRouter()

# In-memory session storage (would be Redis in production)
sessions: dict[str, dict[str, Any]] = {}


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """Handle chat message and return response with optional UI update."""
    session_id = request.session_id or "default"

    if session_id not in sessions:
        sessions[session_id] = {
            "session_id": session_id,
            "created_at": "2024-01-01T00:00:00Z",
            "status": "active",
        }

    # Placeholder: would integrate with orchestrator
    response_content = f"Echo: {request.messages[-1].content if request.messages else ''}"

    return ChatResponse(
        message=Message(role="assistant", content=response_content),
        session_id=session_id,
        ui_document=None,
    )


@router.post("/actions", response_model=ActionResponse)
async def handle_action(request: ActionRequest) -> ActionResponse:
    """Handle UI action and return result with optional UI update."""
    session_id = request.session_id or "default"

    # Placeholder: would integrate with orchestrator
    return ActionResponse(
        success=True,
        result={"action": request.action_id, "params": request.params},
        error=None,
        ui_document=None,
    )


@router.get("/sessions/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str) -> SessionResponse:
    """Get session information."""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    data = sessions[session_id]
    return SessionResponse(
        session_id=data["session_id"],
        created_at=data["created_at"],
        status=data["status"],
    )


@router.post("/sessions", response_model=SessionResponse)
async def create_session() -> SessionResponse:
    """Create a new session."""
    import uuid

    session_id = str(uuid.uuid4())
    sessions[session_id] = {
        "session_id": session_id,
        "created_at": "2024-01-01T00:00:00Z",
        "status": "active",
    }

    return SessionResponse(
        session_id=session_id,
        created_at=sessions[session_id]["created_at"],
        status="active",
    )


@router.get("/ui-schema", response_model=UISchemaResponse)
async def get_ui_schema() -> UISchemaResponse:
    """Get UI schema with supported block types and actions."""
    return UISchemaResponse(
        version="1.0",
        block_types=[
            "text",
            "stat",
            "card",
            "section",
            "list",
            "table",
            "chart",
            "form",
            "selector",
            "timeline",
            "image",
            "action_bar",
        ],
        action_types=["button", "link", "submit", "navigate"],
    )