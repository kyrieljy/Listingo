"""Storage adapters used by rate limiting and abuse defenses."""

from backend.app.core.storage.base import (
    IncrementResult,
    RateLimitStorage,
    StorageItem,
    WriteResult,
)
from backend.app.core.storage.memory import MemoryStorage
from backend.app.core.storage.redis import RedisStorage

__all__ = [
    "IncrementResult",
    "MemoryStorage",
    "RedisStorage",
    "RateLimitStorage",
    "StorageItem",
    "WriteResult",
]
