"""Model registry and configuration."""

from dataclasses import dataclass


@dataclass
class ModelConfig:
    """Configuration for an LLM model."""
    name: str
    provider: str
    supports_vision: bool = False
    supports_function_calling: bool = False
    max_tokens: int = 4096


# Default model registry
MODEL_REGISTRY: dict[str, ModelConfig] = {
    # Anthropic models
    "claude-3-5-sonnet-latest": ModelConfig(
        name="claude-3-5-sonnet-latest",
        provider="anthropic",
        supports_vision=True,
        supports_function_calling=True,
    ),
    "claude-3-opus-latest": ModelConfig(
        name="claude-3-opus-latest",
        provider="anthropic",
        supports_vision=True,
        supports_function_calling=True,
    ),
    # OpenAI models
    "gpt-4o": ModelConfig(
        name="gpt-4o",
        provider="openai",
        supports_vision=True,
        supports_function_calling=True,
    ),
    "gpt-4o-mini": ModelConfig(
        name="gpt-4o-mini",
        provider="openai",
        supports_vision=True,
        supports_function_calling=True,
    ),
    "gpt-4-turbo": ModelConfig(
        name="gpt-4-turbo",
        provider="openai",
        supports_vision=True,
        supports_function_calling=True,
    ),
    # Ollama models (local)
    "llama3": ModelConfig(
        name="llama3",
        provider="ollama",
        supports_vision=False,
        supports_function_calling=False,
        max_tokens=8192,
    ),
    "mistral": ModelConfig(
        name="mistral",
        provider="ollama",
        supports_vision=False,
        supports_function_calling=False,
    ),
    # DeepSeek
    "deepseek-chat": ModelConfig(
        name="deepseek-chat",
        provider="deepseek",
        supports_vision=False,
        supports_function_calling=True,
    ),
}


def register_model(config: ModelConfig) -> None:
    """Register a new model in the registry."""
    MODEL_REGISTRY[config.name] = config


def get_model_config(model: str) -> ModelConfig | None:
    """Get configuration for a model."""
    return MODEL_REGISTRY.get(model)