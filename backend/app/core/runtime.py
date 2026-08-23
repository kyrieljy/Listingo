from __future__ import annotations

"""Application runtime state shared by security features and derived-state caches.

PostgreSQL remains the only source of business facts. This service layers
optional, TTL-bounded derived state (caches/counters), short-lived snapshots
(session metadata, batch progress) and correctness tokens (locks) on the same
storage adapter already used by rate limiting.
"""

import json
import logging
import secrets
from dataclasses import dataclass
from typing import Callable, TypeVar

from backend.app.core.storage.base import RateLimitStorage, StorageUnavailableError
from backend.app.core.storage.keys import cache_key, cache_version_key


logger = logging.getLogger(__name__)
T = TypeVar("T")


@dataclass(frozen=True)
class RuntimeTTLs:
    """TTLs are injected from Settings so operations can tune them per deployment."""

    cache: int = 300
    cache_version: int = 7 * 24 * 60 * 60
    session: int = 300
    batch_status: int = 3
    lock: int = 30
    metric: int = 2 * 24 * 60 * 60
    ocr: int = 3600


class RuntimeStateService:
    def __init__(self, storage: RateLimitStorage, *, ttls: RuntimeTTLs | None = None) -> None:
        self.storage = storage
        self.ttls = ttls or RuntimeTTLs()

    def get_json(self, key: str) -> object | None:
        item = self.storage.get(key)
        if item is None:
            return None
        try:
            return json.loads(item.value)
        except (TypeError, ValueError):
            # Corrupt cache entries self-heal; the source of truth is always PostgreSQL.
            self.storage.delete(key)
            return None

    def set_json(self, key: str, value: object, ttl: int) -> None:
        self.storage.setex(key, json.dumps(value, ensure_ascii=False, default=str), ttl, allow_eviction=True)

    def delete(self, key: str) -> bool:
        return self.storage.delete(key)

    def cached(self, key: str, ttl: int, producer: Callable[[], T]) -> T:
        """Cache-aside helper for optional performance caches (fail-open)."""
        try:
            cached = self.get_json(key)
        except StorageUnavailableError:
            logger.warning("Runtime cache read failed; falling back to PostgreSQL", exc_info=True)
            return producer()
        if cached is not None:
            return cached  # type: ignore[return-value]
        value = producer()
        try:
            self.set_json(key, value, ttl)
        except StorageUnavailableError:
            logger.warning("Runtime cache write failed; serving uncached value", exc_info=True)
        return value

    def cached_versioned(
        self,
        domain: str,
        identifier: str,
        producer: Callable[[], T],
    ) -> T:
        """Cache a value under a domain generation, including generation failures.

        A version-key outage must not turn an optional cache into a request
        failure. In that case we execute the producer directly; the next healthy
        request can resume versioned caching.
        """
        try:
            version = self.cache_version(domain, self.ttls.cache_version)
        except StorageUnavailableError:
            logger.warning("Runtime cache version read failed; using PostgreSQL", exc_info=True)
            return producer()
        payload = self.cached(
            cache_key(domain, f"{version}:{identifier}"),
            self.ttls.cache,
            lambda: {"found": True, "value": producer()},
        )
        # `None` can itself be a cached database fact (for example a missing
        # provider); the wrapper keeps it distinct from a cache miss.
        if isinstance(payload, dict) and set(payload) == {"found", "value"} and payload["found"] is True:
            return payload["value"]  # type: ignore[no-any-return]
        return payload

    def cache_version(self, domain: str, ttl: int) -> str:
        """Read (and refresh) a cache-domain generation used in data keys."""
        key = cache_version_key(domain)
        item = self.storage.get(key)
        if item is None:
            created = self.storage.set_if_absent(key, "1", ttl, allow_eviction=True)
            if created.success:
                return "1"
            item = self.storage.get(key)
            if item is None:
                return "1"
        else:
            self.storage.expire(key, ttl)
        value = str(item.value)
        if not value.isdigit():
            # A corrupt generation must not poison new writes; rebuild from 1.
            self.storage.delete(key)
            self.storage.set_if_absent(key, "1", ttl)
            return "1"
        return value

    def get_json_best_effort(self, key: str) -> object | None:
        try:
            return self.get_json(key)
        except StorageUnavailableError:
            logger.warning("Runtime cache read skipped; storage unavailable", exc_info=True)
            return None

    def set_json_best_effort(self, key: str, value: object, ttl: int) -> None:
        try:
            self.set_json(key, value, ttl)
        except StorageUnavailableError:
            logger.warning("Runtime cache write skipped; storage unavailable", exc_info=True)

    def delete_best_effort(self, key: str) -> None:
        try:
            self.delete(key)
        except StorageUnavailableError:
            logger.warning("Runtime cache invalidation skipped; storage unavailable", exc_info=True)

    def invalidate(self, domain: str, ttl: int) -> int:
        """Bump a domain generation; old data keys expire by their own TTL."""
        return self.storage.incr(cache_version_key(domain), ttl).value

    def invalidate_best_effort(self, domain: str) -> None:
        """Invalidation is optional: TTL still bounds staleness if Redis is down."""
        try:
            self.invalidate(domain, self.ttls.cache_version)
        except StorageUnavailableError:
            logger.warning("Runtime cache invalidation failed; TTL will bound staleness", exc_info=True)

    def acquire_lock(self, key: str, ttl: int) -> str | None:
        """Acquire a token lock; storage failures propagate (fail-closed)."""
        token = secrets.token_urlsafe(16)
        result = self.storage.set_if_absent(key, token, ttl, allow_eviction=False)
        return token if result.success else None

    def release_lock(self, key: str, token: str) -> bool:
        """Release only our token so expired holders cannot delete newer locks."""
        return self.storage.delete_if_equal(key, token)

    def increment(self, key: str, ttl: int) -> int:
        return self.storage.incr(key, ttl).value

    def increment_best_effort(self, key: str, ttl: int) -> None:
        try:
            self.increment(key, ttl)
        except StorageUnavailableError:
            logger.warning("Runtime metric increment skipped; storage unavailable", exc_info=True)


_default_runtime: RuntimeStateService | None = None


def configure_default_runtime(service: RuntimeStateService | None) -> None:
    global _default_runtime
    _default_runtime = service


def reset_default_runtime(service: RuntimeStateService) -> None:
    """Only clear the default when it still belongs to the shutting-down app."""
    global _default_runtime
    if _default_runtime is service:
        _default_runtime = None


def default_runtime() -> RuntimeStateService | None:
    """Return the app runtime when available; pure unit tests run uncached/unlocked."""
    return _default_runtime
