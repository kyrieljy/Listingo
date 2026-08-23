from __future__ import annotations

import hashlib
import math
import re
import time
from dataclasses import dataclass
from enum import Enum

from fastapi import Request

from backend.app.config import Settings
from backend.app.core.storage.base import RateLimitStorage
from backend.app.core.storage.memory import MemoryStorage, SINGLE_PROCESS_WARNING
from backend.app.core.storage.redis import RedisStorage


NONCE_TTL_SECONDS = 60
_NONCE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{16,128}$")


class NonceStatus(str, Enum):
    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"
    INVALID = "invalid"
    CAPACITY_EXCEEDED = "capacity_exceeded"


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    limit: int
    count: int
    remaining: int
    reset_in_seconds: int


@dataclass(frozen=True)
class NonceResult:
    status: NonceStatus
    expires_in_seconds: int | None = None


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()[:80]
    return (request.client.host if request.client else "")[:80]


def _window(now: float, window: int) -> tuple[int, int, int]:
    window_id = math.floor(now / window)
    reset_at = (window_id + 1) * window
    return window_id, max(1, math.ceil(reset_at - now)), math.ceil(reset_at - now)


class RateLimitService:
    def __init__(self, storage: RateLimitStorage) -> None:
        self.storage = storage

    def consume_rate_limit(self, key: str, limit: int, window: int) -> RateLimitResult:
        if limit < 1 or window < 1:
            raise ValueError("Rate-limit limit and window must be positive")
        window_id, reset_in, ttl = _window(time.time(), window)
        counter = self.storage.incr(f"rate:{key}:{window_id}", ttl)
        remaining = max(limit - counter.value, 0)
        return RateLimitResult(
            allowed=counter.value <= limit,
            limit=limit,
            count=counter.value,
            remaining=remaining,
            reset_in_seconds=reset_in,
        )

    def check_rate_limit(self, key: str, limit: int, window: int) -> bool:
        return self.consume_rate_limit(key, limit, window).allowed

    def consume_nonce(self, nonce: str, ttl: int = NONCE_TTL_SECONDS) -> NonceResult:
        normalized = (nonce or "").strip()
        if ttl != NONCE_TTL_SECONDS or not _NONCE_PATTERN.fullmatch(normalized):
            return NonceResult(status=NonceStatus.INVALID)
        nonce_key = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        result = self.storage.set_if_absent(
            f"nonce:{nonce_key}",
            "1",
            ttl,
            allow_eviction=False,
        )
        if result.success:
            return NonceResult(status=NonceStatus.ACCEPTED, expires_in_seconds=result.expires_in_seconds)
        existing = self.storage.get(f"nonce:{nonce_key}")
        if existing is not None:
            return NonceResult(status=NonceStatus.DUPLICATE, expires_in_seconds=existing.expires_in_seconds)
        return NonceResult(status=NonceStatus.CAPACITY_EXCEEDED)

    def check_and_consume_nonce(self, nonce: str, ttl: int = NONCE_TTL_SECONDS) -> bool:
        return self.consume_nonce(nonce, ttl).status is NonceStatus.ACCEPTED

    def record_failure_and_block(
        self,
        ip: str,
        fail_limit: int = 5,
        window: int = 60,
        block_seconds: int = 1800,
    ) -> bool:
        if fail_limit < 1 or window < 1 or block_seconds < 1:
            raise ValueError("Failure limits, window, and block duration must be positive")
        _, _, ttl = _window(time.time(), window)
        failure_key = self._failure_key(ip)
        failures = self.storage.incr(failure_key, ttl)
        if failures.value < fail_limit:
            return False
        self.storage.setex(self._block_key(ip), "1", block_seconds)
        self.storage.delete(failure_key)
        return True

    def clear_login_failures(self, ip: str) -> None:
        self.storage.delete(self._failure_key(ip))

    def is_ip_blocked(self, ip: str) -> bool:
        return self.storage.get(self._block_key(ip)) is not None

    def block_ttl_seconds(self, ip: str) -> int | None:
        item = self.storage.get(self._block_key(ip))
        return item.expires_in_seconds if item else None

    def _failure_key(self, ip: str) -> str:
        window_id = math.floor(time.time() / 60)
        return f"login_failure:{ip}:{window_id}"

    @staticmethod
    def _block_key(ip: str) -> str:
        return f"login_block:{ip}"

    def close(self) -> None:
        self.storage.close()

    def start(self) -> None:
        self.storage.start_cleanup_thread()


def rate_limit_headers(result: RateLimitResult) -> dict[str, str]:
    return {
        "X-RateLimit-Limit": str(result.limit),
        "X-RateLimit-Remaining": str(result.remaining),
        "X-RateLimit-Reset": str(result.reset_in_seconds),
    }


def create_rate_limiter(settings: Settings) -> RateLimitService:
    if settings.storage_backend == "redis":
        storage: RateLimitStorage = RedisStorage(
            url=settings.redis_url,
            key_prefix=settings.redis_key_prefix,
            connect_timeout_seconds=settings.redis_connect_timeout_seconds,
            socket_timeout_seconds=settings.redis_socket_timeout_seconds,
        )
    elif settings.storage_backend == "memory":
        storage = MemoryStorage(
            max_size=settings.rate_limit_max_size,
            cleanup_interval_seconds=settings.rate_limit_cleanup_interval_seconds,
            start_cleanup_thread=False,
        )
    else:
        raise ValueError(f"Unsupported rate-limit storage backend: {settings.storage_backend}")
    return RateLimitService(storage)


_default_service: RateLimitService | None = None


def _default_rate_limiter() -> RateLimitService:
    global _default_service
    if _default_service is None:
        raise RuntimeError("Rate limiter has not been initialized with configured storage")
    return _default_service


def check_rate_limit(key: str, limit: int, window: int) -> bool:
    return _default_rate_limiter().check_rate_limit(key, limit, window)


def check_and_consume_nonce(nonce: str, ttl: int = NONCE_TTL_SECONDS) -> bool:
    return _default_rate_limiter().check_and_consume_nonce(nonce, ttl)


def record_failure_and_block(
    ip: str,
    fail_limit: int = 5,
    window: int = 60,
    block_seconds: int = 1800,
) -> bool:
    return _default_rate_limiter().record_failure_and_block(ip, fail_limit, window, block_seconds)


__all__ = [
    "NONCE_TTL_SECONDS",
    "NonceResult",
    "NonceStatus",
    "RateLimitResult",
    "RateLimitService",
    "SINGLE_PROCESS_WARNING",
    "check_and_consume_nonce",
    "check_rate_limit",
    "client_ip",
    "create_rate_limiter",
    "rate_limit_headers",
    "record_failure_and_block",
]
