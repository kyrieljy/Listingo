from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class StorageItem:
    value: str
    expires_in_seconds: int | None = None


@dataclass(frozen=True)
class IncrementResult:
    value: int
    expires_in_seconds: int


@dataclass(frozen=True)
class WriteResult:
    success: bool
    expires_in_seconds: int | None = None


class RateLimitStorage(ABC):
    """The backend-neutral contract shared by memory and future Redis storage."""

    @abstractmethod
    def incr(self, key: str, ttl: int) -> IncrementResult:
        """Atomically increment a value and initialize its TTL on the first write."""

    @abstractmethod
    def exists(self, key: str) -> bool:
        """Return whether a live key exists."""

    @abstractmethod
    def setex(
        self,
        key: str,
        value: str,
        ttl: int,
        *,
        allow_eviction: bool = True,
    ) -> WriteResult:
        """Set a value with an absolute TTL, optionally evicting old records."""

    @abstractmethod
    def get(self, key: str) -> StorageItem | None:
        """Return a live value and its remaining TTL."""

    @abstractmethod
    def delete(self, key: str) -> bool:
        """Delete a key and report whether it existed."""

    @abstractmethod
    def expire(self, key: str, ttl: int) -> bool:
        """Apply a new TTL to an existing live key."""

    @abstractmethod
    def set_if_absent(
        self,
        key: str,
        value: str,
        ttl: int,
        *,
        allow_eviction: bool = False,
    ) -> WriteResult:
        """Atomically write only when the key is absent."""

    @abstractmethod
    def cleanup_expired(self) -> int:
        """Synchronously remove expired records and return the removed count."""

    @abstractmethod
    def start_cleanup_thread(self) -> None:
        """Start adapter-owned periodic cleanup for an application lifespan."""

    @abstractmethod
    def close(self) -> None:
        """Release background resources owned by the adapter."""
