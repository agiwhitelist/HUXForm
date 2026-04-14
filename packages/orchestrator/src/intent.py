"""Intent classification for user input."""

from enum import Enum
from dataclasses import dataclass


class IntentType(Enum):
    """Classification of user intent."""
    QUERY = "query"
    ACTION = "action"
    CREATE = "create"
    MODIFY = "modify"
    DELETE = "delete"
    SEARCH = "search"
    HELP = "help"
    UNKNOWN = "unknown"


@dataclass
class Intent:
    """Classified user intent."""
    type: IntentType
    confidence: float
    entities: dict
    raw_input: str


class IntentClassifier:
    """Classifies user input into intents."""

    def __init__(self, llm_router=None):
        self.llm_router = llm_router

    async def classify(self, user_input: str) -> Intent:
        """Classify user input into intent type."""
        # Simple rule-based classification for now
        # Would integrate with LLM for complex classification

        input_lower = user_input.lower().strip()

        # Check for question patterns
        if any(q in input_lower for q in ["what", "how", "why", "when", "where", "who"]):
            intent_type = IntentType.QUERY
        # Check for action words
        elif any(a in input_lower for a in ["create", "make", "build", "add", "do"]):
            intent_type = IntentType.CREATE
        # Check for modification words
        elif any(m in input_lower for m in ["update", "change", "modify", "edit", "fix"]):
            intent_type = IntentType.MODIFY
        # Check for deletion words
        elif any(d in input_lower for d in ["delete", "remove", "cancel", "stop"]):
            intent_type = IntentType.DELETE
        # Check for search words
        elif any(s in input_lower for s in ["find", "search", "look", "show", "list"]):
            intent_type = IntentType.SEARCH
        # Check for help
        elif any(h in input_lower for h in ["help", "assist", "support"]):
            intent_type = IntentType.HELP
        else:
            intent_type = IntentType.UNKNOWN

        # Calculate simple confidence based on keyword matches
        confidence = 0.7 if intent_type != IntentType.UNKNOWN else 0.3

        return Intent(
            type=intent_type,
            confidence=confidence,
            entities={},
            raw_input=user_input,
        )