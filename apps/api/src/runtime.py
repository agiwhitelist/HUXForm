"""Process-wide runtime singletons.

We keep a single Registry instance and let modules that need it import
`registry()` rather than pass it through every call chain. The
FastAPI `lifespan` hook initializes everything via `boot()`.
"""

from __future__ import annotations

from typing import Optional

from .tasks import Registry


_REGISTRY: Optional[Registry] = None


def set_registry(r: Registry) -> None:
    global _REGISTRY
    _REGISTRY = r


def registry() -> Registry:
    if _REGISTRY is None:
        raise RuntimeError("Registry not initialized")
    return _REGISTRY
