from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum


class StorageUnavailableError(RuntimeError):
    """Raised when a runtime storage backend cannot service a request."""


class HashConsumeStatus(str, Enum):
    ACCEPTED = "accepted"
    MISSING = "missing"
    LIMIT_EXCEEDED = "limit_exceeded"
    MISMATCH = "mismatch"


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
    def set_persistent_many(self, items: dict[str, str]) -> None:
        """Atomically replace durable values without TTL or LRU eviction."""

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
    def expire_if_equal(self, key: str, expected_value: str, ttl: int) -> bool:
        """Renew a live key's TTL only when its current value matches."""

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

    @abstractmethod
    def reserve_sliding_window(
        self,
        key: str,
        reservation_token: str,
        limit: int,
        window: int,
    ) -> bool:
        """Atomically reserve one slot in a rolling time window."""

    @abstractmethod
    def release_sliding_window(self, key: str, reservation_token: str) -> bool:
        """Release a rolling-window reservation without affecting others."""

    @abstractmethod
    def delete_if_equal(self, key: str, expected_value: str) -> bool:
        """Delete a live key only when its current value matches."""

    @abstractmethod
    def consume_hash_once(
        self,
        key: str,
        attempts_key: str,
        expected_value: str,
        ttl: int,
        max_attempts: int,
    ) -> HashConsumeStatus:
        """Atomically compare a hash and enforce its attempt budget."""

    @abstractmethod
    def queue_push(self, key: str, value: str) -> None:
        """Append a durable runtime queue element."""

    @abstractmethod
    def queue_pop(self, key: str) -> str | None:
        """Remove and return the oldest queue element."""

    @abstractmethod
    def queue_remove(self, key: str, value: str) -> bool:
        """Remove every matching queue element and report whether one existed."""

    @abstractmethod
    def queue_length(self, key: str) -> int:
        """Return the number of queued elements."""

    @abstractmethod
    def queue_clear(self, key: str) -> bool:
        """Clear a rebuildable queue and report whether it existed."""

    @abstractmethod
    def queue_items(self, key: str) -> list[str]:
        """Return queue elements in consumption order for diagnostics."""
