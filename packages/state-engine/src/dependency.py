class DependencyTracker:
    def __init__(self):
        self._dirty: dict[str, bool] = {}
        self._dependents: dict[str, list[str]] = {}

    def register_dependency(self, key: str, dependent: str) -> None:
        if key not in self._dependents:
            self._dependents[key] = []
        self._dependents[key].append(dependent)

    def invalidate(self, key: str) -> None:
        self._dirty[key] = True
        for dependent in self._dependents.get(key, []):
            self.invalidate(dependent)

    def get_dirty(self) -> dict[str, bool]:
        return {k: v for k, v in self._dirty.items() if v}

    def clear(self, key: str) -> None:
        self._dirty[key] = False

    def clear_all(self) -> None:
        self._dirty.clear()
