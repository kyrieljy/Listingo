from __future__ import annotations

import math
import threading
from collections import OrderedDict
from dataclasses import dataclass
from time import monotonic
from typing import Callable

from backend.app.core.storage.base import IncrementResult, RateLimitStorage, StorageItem, WriteResult


SINGLE_PROCESS_WARNING = (
    "WARNING: Rate limiting is running in MEMORY mode. "
    "DO NOT scale horizontally or set Gunicorn workers > 1."
)


@dataclass
class _MemoryEntry:
    value: str
    expires_at: float | None


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
        return len(expired)

    def _make_room(self, key: str, *, allow_eviction: bool) -> bool:
        self._remove_expired_locked()
        if key in self._items or len(self._items) < self._max_size:
            return True
        if not allow_eviction:
            return False
        self._items.popitem(last=False)
        return True

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
            self._items[key] = _MemoryEntry(value=value, expires_at=expires_at)
            return WriteResult(success=True, expires_in_seconds=self._entry_ttl(self._items[key]))

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
            self._items[key] = _MemoryEntry(value=value, expires_at=self._clock() + ttl)
            return WriteResult(success=True, expires_in_seconds=self._entry_ttl(self._items[key]))

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
