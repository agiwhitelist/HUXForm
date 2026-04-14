"""Pydantic models for API requests and responses."""

from pydantic import BaseModel, Field
from typing import Any


class Message(BaseModel):
    """Chat message model."""
    role: str
    content: str


class ChatRequest(BaseModel):
    """Chat request model."""
    messages: list[Message]
    model: str | None = None
    session_id: str | None = None


class ActionRequest(BaseModel):
    """Action request model."""
    action_id: str
    params: dict[str, Any] = Field(default_factory=dict)
    session_id: str | None = None


class ActionResponse(BaseModel):
    """Action response model."""
    success: bool
    result: Any | None = None
    error: str | None = None
    ui_document: dict | None = None


class ChatResponse(BaseModel):
    """Chat response model."""
    message: Message
    session_id: str
    ui_document: dict | None = None


class SessionResponse(BaseModel):
    """Session info response."""
    session_id: str
    created_at: str
    status: str


class UISchemaResponse(BaseModel):
    """UI schema response."""
    version: str
    block_types: list[str]
    action_types: list[str]