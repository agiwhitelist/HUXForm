class MemoryBridge:
    async def sync_to_long_term(self, state: dict) -> None:
        pass

    async def load_from_long_term(self, memory_ref: str) -> dict:
        return {}
