from __future__ import annotations

import math
import threading
from collections import OrderedDict, deque
from dataclasses import dataclass
from time import monotonic
from typing import Callable

from backend.app.core.storage.base import (
    HashConsumeStatus,
    IncrementResult,
    RateLimitStorage,
    StorageItem,
    WriteResult,
)


SINGLE_PROCESS_WARNING = (
    "WARNING: Rate limiting is running in MEMORY mode. "
    "DO NOT scale horizontally or set Gunicorn workers > 1."
)


@dataclass
class _MemoryEntry:
    value: str
    expires_at: float | None
    evictable: bool = True


@dataclass
class _SlidingWindowEntry:
    expires_at: float


class MemoryStorage(RateLimitStorage):
    """Bounded process-local storage.

    WARNING: Rate limiting is running in MEMORY mode. DO NOT scale horizontally
    or set Gunicorn workers > 1. All counters and blocks are lost on restart.
    """

    def __init__(
        self,
        *,
        max_size: int = 10_000,
        cleanup_interval_seconds: int = 30,
        start_cleanup_thread: bool = True,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if max_size < 1:
            raise ValueError("max_size must be at least 1")
        if cleanup_interval_seconds < 1:
            raise ValueError("cleanup_interval_seconds must be at least 1 second")
        self._max_size = max_size
        self._cleanup_interval = cleanup_interval_seconds
        self._clock = clock
        self._items: OrderedDict[str, _MemoryEntry] = OrderedDict()
        self._queues: dict[str, deque[str]] = {}
        self._sliding_windows: OrderedDict[str, OrderedDict[str, _SlidingWindowEntry]] = OrderedDict()
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._cleanup_thread: threading.Thread | None = None
        if start_cleanup_thread:
            self.start_cleanup_thread()

    def start_cleanup_thread(self) -> None:
        """Start the periodic janitor once for an application lifespan."""
        if self._cleanup_thread is not None or self._stop_event.is_set():
            return
        self._cleanup_thread = threading.Thread(
            target=self._cleanup_loop,
            name="listingo-rate-limit-cleanup",
            daemon=True,
        )
        self._cleanup_thread.start()

    @property
    def max_size(self) -> int:
        return self._max_size

    @property
    def size(self) -> int:
        with self._lock:
            self._remove_expired_locked()
            return len(self._items)

    def _ttl(self, ttl: int) -> None:
        if ttl < 1:
            raise ValueError("TTL must be at least 1 second")

    def _entry_ttl(self, entry: _MemoryEntry) -> int | None:
        if entry.expires_at is None:
            return None
        remaining = math.ceil(entry.expires_at - self._clock())
        return max(remaining, 1)

    def _live_entry(self, key: str) -> _MemoryEntry | None:
        entry = self._items.get(key)
        if entry is None:
            return None
        if entry.expires_at is not None and entry.expires_at <= self._clock():
            del self._items[key]
            return None
        self._items.move_to_end(key)
        return entry

    def _remove_expired_locked(self) -> int:
        now = self._clock()
        expired = [
            key
            for key, entry in self._items.items()
            if entry.expires_at is not None and entry.expires_at <= now
        ]
        for key in expired:
            del self._items[key]
        expired_windows = 0
        for key, entries in list(self._sliding_windows.items()):
            window_expired = [token for token, entry in entries.items() if entry.expires_at <= now]
            for token in window_expired:
                del entries[token]
                expired_windows += 1
            if not entries:
                del self._sliding_windows[key]
        return len(expired) + expired_windows

    def _make_room(self, key: str, *, allow_eviction: bool) -> bool:
        self._remove_expired_locked()
        if key in self._items or len(self._items) < self._max_size:
            return True
        # Correctness keys (nonce, locks) opt out of LRU; only derived-state
        # entries may surrender their slot. The new entry still records whether
        # it can be evicted by a later derived-state write.
        for candidate, entry in self._items.items():
            if entry.evictable:
                del self._items[candidate]
                return True
        return False

    def incr(self, key: str, ttl: int) -> IncrementResult:
        self._ttl(ttl)
        with self._lock:
            if not self._make_room(key, allow_eviction=True):
                raise RuntimeError("Unable to reserve memory storage capacity")
            entry = self._live_entry(key)
            if entry is None:
                entry = _MemoryEntry(value="1", expires_at=self._clock() + ttl)
                self._items[key] = entry
                count = 1
            else:
                count = int(entry.value) + 1
                entry.value = str(count)
                self._items.move_to_end(key)
            return IncrementResult(value=count, expires_in_seconds=self._entry_ttl(entry) or ttl)

    def exists(self, key: str) -> bool:
        with self._lock:
            self._remove_expired_locked()
            return self._live_entry(key) is not None

    def setex(
        self,
        key: str,
        value: str,
        ttl: int,
        *,
        allow_eviction: bool = True,
    ) -> WriteResult:
        self._ttl(ttl)
        with self._lock:
            if not self._make_room(key, allow_eviction=allow_eviction):
                return WriteResult(success=False)
            expires_at = self._clock() + ttl
            self._items[key] = _MemoryEntry(value=value, expires_at=expires_at, evictable=allow_eviction)
            return WriteResult(success=True, expires_in_seconds=self._entry_ttl(self._items[key]))

    def set_persistent_many(self, items: dict[str, str]) -> None:
        with self._lock:
            # Persistent facts are replaced as one visibility unit while the lock is held.
            for key, value in items.items():
                self._items[key] = _MemoryEntry(value=value, expires_at=None, evictable=False)

    def get(self, key: str) -> StorageItem | None:
        with self._lock:
            self._remove_expired_locked()
            entry = self._live_entry(key)
            if entry is None:
                return None
            return StorageItem(value=entry.value, expires_in_seconds=self._entry_ttl(entry))

    def delete(self, key: str) -> bool:
        with self._lock:
            self._remove_expired_locked()
            return self._items.pop(key, None) is not None

    def expire(self, key: str, ttl: int) -> bool:
        self._ttl(ttl)
        with self._lock:
            self._remove_expired_locked()
            entry = self._live_entry(key)
            if entry is None:
                return False
            entry.expires_at = self._clock() + ttl
            self._items.move_to_end(key)
            return True

    def expire_if_equal(self, key: str, expected_value: str, ttl: int) -> bool:
        self._ttl(ttl)
        with self._lock:
            self._remove_expired_locked()
            entry = self._live_entry(key)
            if entry is None or entry.value != expected_value:
                return False
            entry.expires_at = self._clock() + ttl
            return True

    def set_if_absent(
        self,
        key: str,
        value: str,
        ttl: int,
        *,
        allow_eviction: bool = False,
    ) -> WriteResult:
        self._ttl(ttl)
        with self._lock:
            if not self._make_room(key, allow_eviction=allow_eviction):
                return WriteResult(success=False)
            if self._live_entry(key) is not None:
                return WriteResult(success=False)
            self._items[key] = _MemoryEntry(value=value, expires_at=self._clock() + ttl, evictable=allow_eviction)
            return WriteResult(success=True, expires_in_seconds=self._entry_ttl(self._items[key]))

    def _reserve_sliding_window_locked(
        self,
        key: str,
        reservation_token: str,
        limit: int,
        window: int,
    ) -> bool:
        self._ttl(window)
        if limit < 1:
            raise ValueError("Sliding-window limit must be positive")
        if key not in self._sliding_windows:
            self._sliding_windows[key] = OrderedDict[str, _SlidingWindowEntry]()
        entries = self._sliding_windows[key]
        now = self._clock()
        expired = [token for token, entry in entries.items() if entry.expires_at <= now]
        for token in expired:
            del entries[token]
        if len(entries) >= limit:
            return False
        entries[reservation_token] = _SlidingWindowEntry(expires_at=now + window)
        return True

    def reserve_sliding_window(
        self,
        key: str,
        reservation_token: str,
        limit: int,
        window: int,
    ) -> bool:
        with self._lock:
            return self._reserve_sliding_window_locked(key, reservation_token, limit, window)

    def release_sliding_window(self, key: str, reservation_token: str) -> bool:
        with self._lock:
            entries = self._sliding_windows.get(key)
            return entries.pop(reservation_token, None) is not None

    def delete_if_equal(self, key: str, expected_value: str) -> bool:
        with self._lock:
            self._remove_expired_locked()
            entry = self._live_entry(key)
            if entry is None or entry.value != expected_value:
                return False
            del self._items[key]
            return True

    def consume_hash_once(
        self,
        key: str,
        attempts_key: str,
        expected_value: str,
        ttl: int,
        max_attempts: int,
    ) -> HashConsumeStatus:
        self._ttl(ttl)
        if max_attempts < 1:
            raise ValueError("Maximum hash attempts must be positive")
        with self._lock:
            code = self._live_entry(key)
            if code is None:
                return HashConsumeStatus.MISSING
            attempts = self._live_entry(attempts_key)
            attempt_count = int(attempts.value) if attempts is not None else 0
            if attempt_count >= max_attempts:
                return HashConsumeStatus.LIMIT_EXCEEDED
            if code.value != expected_value:
                self._items[attempts_key] = _MemoryEntry(
                    value=str(attempt_count + 1),
                    expires_at=self._clock() + ttl,
                )
                return HashConsumeStatus.MISMATCH
            del self._items[key]
            self._items.pop(attempts_key, None)
            return HashConsumeStatus.ACCEPTED

    def queue_push(self, key: str, value: str) -> None:
        # Queues are correctness state and deliberately bypass TTL/LRU eviction.
        with self._lock:
            self._queues.setdefault(key, deque()).append(value)

    def queue_pop(self, key: str) -> str | None:
        with self._lock:
            queue = self._queues.get(key)
            if not queue:
                return None
            value = queue.popleft()
            if not queue:
                del self._queues[key]
            return value

    def queue_remove(self, key: str, value: str) -> bool:
        with self._lock:
            queue = self._queues.get(key)
            if queue is None:
                return False
            removed = value in queue
            try:
                while True:
                    queue.remove(value)
            except ValueError:
                pass
            if not queue:
                del self._queues[key]
            return removed

    def queue_length(self, key: str) -> int:
        with self._lock:
            return len(self._queues.get(key, ()))

    def queue_clear(self, key: str) -> bool:
        with self._lock:
            return self._queues.pop(key, None) is not None

    def queue_items(self, key: str) -> list[str]:
        with self._lock:
            return list(self._queues.get(key, ()))

    def cleanup_expired(self) -> int:
        with self._lock:
            return self._remove_expired_locked()

    def _cleanup_loop(self) -> None:
        while not self._stop_event.wait(self._cleanup_interval):
            self.cleanup_expired()

    def close(self) -> None:
        self._stop_event.set()
        thread = self._cleanup_thread
        self._cleanup_thread = None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(0.1, self._cleanup_interval))
