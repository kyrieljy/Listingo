from __future__ import annotations

from redis import Redis as RedisClient
from redis.connection import ConnectionPool
from redis.exceptions import RedisError, WatchError

from backend.app.core.storage.base import (
    HashConsumeStatus,
    IncrementResult,
    RateLimitStorage,
    StorageItem,
    StorageUnavailableError,
    WriteResult,
)


class RedisStorage(RateLimitStorage):
    """Redis-backed storage shared by every backend worker."""

    def __init__(
        self,
        *,
        url: str,
        key_prefix: str = "listingo",
        connect_timeout_seconds: float = 2.0,
        socket_timeout_seconds: float = 2.0,
        max_connections: int = 50,
        health_check_interval_seconds: int = 30,
        client: RedisClient | None = None,
    ) -> None:
        if not key_prefix or any(char.isspace() for char in key_prefix):
            raise ValueError("Redis key prefix must not be empty or contain whitespace")
        if max_connections < 1:
            raise ValueError("Redis max_connections must be at least 1")
        if health_check_interval_seconds < 0:
            raise ValueError("Redis health_check_interval_seconds must not be negative")
        self._prefix = key_prefix
        if client is not None:
            # 测试或外部注入的客户端（如 FakeRedis）直接复用，跳过连接池构建。
            self._client = client
        else:
            # 显式构建连接池，固定上限与空闲健康检查，避免连接无限增长与僵死连接。
            pool = ConnectionPool.from_url(
                url,
                decode_responses=True,
                socket_connect_timeout=connect_timeout_seconds,
                socket_timeout=socket_timeout_seconds,
                max_connections=max_connections,
                health_check_interval=health_check_interval_seconds,
            )
            self._client = RedisClient(connection_pool=pool)

    @property
    def client(self) -> RedisClient:
        return self._client

    def _key(self, key: str) -> str:
        return f"{self._prefix}:{key}"

    @staticmethod
    def _validate_ttl(ttl: int) -> None:
        if ttl < 1:
            raise ValueError("TTL must be at least 1 second")

    def _call(self, operation, *args, **kwargs):
        try:
            return operation(*args, **kwargs)
        except WatchError:
            raise
        except RedisError as exc:
            raise StorageUnavailableError("Redis storage is unavailable") from exc

    def ping(self) -> None:
        self._call(self._client.ping)

    def incr(self, key: str, ttl: int) -> IncrementResult:
        self._validate_ttl(ttl)
        prefixed_key = self._key(key)
        created = self._call(self._client.set, prefixed_key, 1, ex=ttl, nx=True)
        count = 1 if created else int(self._call(self._client.incr, prefixed_key))
        remaining_ttl = int(self._call(self._client.ttl, prefixed_key))
        return IncrementResult(value=int(count), expires_in_seconds=max(1, int(remaining_ttl)))

    def exists(self, key: str) -> bool:
        return bool(self._call(self._client.exists, self._key(key)))

    def setex(self, key: str, value: str, ttl: int, *, allow_eviction: bool = True) -> WriteResult:
        self._validate_ttl(ttl)
        self._call(self._client.set, self._key(key), value, ex=ttl)
        return WriteResult(success=True, expires_in_seconds=ttl)

    def get(self, key: str) -> StorageItem | None:
        prefixed_key = self._key(key)
        value = self._call(self._client.get, prefixed_key)
        if value is None:
            return None
        ttl = int(self._call(self._client.ttl, prefixed_key))
        return StorageItem(value=value, expires_in_seconds=max(1, ttl))

    def delete(self, key: str) -> bool:
        return bool(self._call(self._client.delete, self._key(key)))

    def expire(self, key: str, ttl: int) -> bool:
        self._validate_ttl(ttl)
        return bool(self._call(self._client.expire, self._key(key), ttl))

    def expire_if_equal(self, key: str, expected_value: str, ttl: int) -> bool:
        self._validate_ttl(ttl)
        prefixed_key = self._key(key)
        for _ in range(3):
            try:
                with self._client.pipeline() as pipeline:
                    pipeline.watch(prefixed_key)
                    if pipeline.get(prefixed_key) != expected_value:
                        pipeline.reset()
                        return False
                    pipeline.multi()
                    pipeline.expire(prefixed_key, ttl)
                    self._call(pipeline.execute)
                    return True
            except WatchError:
                continue
            except RedisError as exc:
                raise StorageUnavailableError("Redis storage is unavailable") from exc
        raise StorageUnavailableError("Redis storage changed too quickly while renewing a value")

    def set_if_absent(
        self,
        key: str,
        value: str,
        ttl: int,
        *,
        allow_eviction: bool = False,
    ) -> WriteResult:
        self._validate_ttl(ttl)
        created = self._call(
            self._client.set,
            self._key(key),
            value,
            ex=ttl,
            nx=True,
        )
        if not created:
            return WriteResult(success=False)
        return WriteResult(success=True, expires_in_seconds=ttl)

    def cleanup_expired(self) -> int:
        return 0

    def start_cleanup_thread(self) -> None:
        return None

    def close(self) -> None:
        self._call(self._client.close)

    def reserve_sliding_window(
        self,
        key: str,
        reservation_token: str,
        limit: int,
        window: int,
    ) -> bool:
        self._validate_ttl(window)
        if limit < 1:
            raise ValueError("Sliding-window limit must be positive")
        prefixed_key = self._key(key)
        for _ in range(3):
            try:
                clock = self._call(self._client.time)
                now = int(clock[0])
                # Integer-second scores may understate age by up to one second; keep that
                # slack on the conservative side rather than expiring quota early.
                self._call(
                    self._client.zremrangebyscore,
                    prefixed_key,
                    "-inf",
                    now - window - 1,
                )
                with self._client.pipeline() as pipeline:
                    pipeline.watch(prefixed_key)
                    active_count = int(pipeline.zcard(prefixed_key))
                    if active_count >= limit:
                        pipeline.reset()
                        return False
                    pipeline.multi()
                    pipeline.zadd(prefixed_key, {reservation_token: now})
                    pipeline.pexpire(prefixed_key, window * 1000)
                    self._call(pipeline.execute)
                    return True
            except WatchError:
                continue
            except RedisError as exc:
                raise StorageUnavailableError("Redis storage is unavailable") from exc
        raise StorageUnavailableError("Redis storage changed too quickly while reserving quota")

    def release_sliding_window(self, key: str, reservation_token: str) -> bool:
        return bool(
            self._call(self._client.zrem, self._key(key), reservation_token)
        )

    def delete_if_equal(self, key: str, expected_value: str) -> bool:
        prefixed_key = self._key(key)
        for _ in range(3):
            try:
                with self._client.pipeline() as pipeline:
                    pipeline.watch(prefixed_key)
                    if pipeline.get(prefixed_key) != expected_value:
                        pipeline.reset()
                        return False
                    pipeline.multi()
                    pipeline.delete(prefixed_key)
                    return bool(self._call(pipeline.execute)[0])
            except WatchError:
                continue
            except RedisError as exc:
                raise StorageUnavailableError("Redis storage is unavailable") from exc
        raise StorageUnavailableError("Redis storage changed too quickly while deleting a value")

    def consume_hash_once(
        self,
        key: str,
        attempts_key: str,
        expected_value: str,
        ttl: int,
        max_attempts: int,
    ) -> HashConsumeStatus:
        self._validate_ttl(ttl)
        if max_attempts < 1:
            raise ValueError("Maximum hash attempts must be positive")
        code_redis_key = self._key(key)
        attempts_redis_key = self._key(attempts_key)
        for _ in range(3):
            try:
                with self._client.pipeline() as pipeline:
                    pipeline.watch(code_redis_key, attempts_redis_key)
                    code = pipeline.get(code_redis_key)
                    if code is None:
                        pipeline.reset()
                        return HashConsumeStatus.MISSING
                    attempts_value = pipeline.get(attempts_redis_key)
                    attempts = int(attempts_value) if attempts_value is not None else 0
                    if attempts >= max_attempts:
                        pipeline.reset()
                        return HashConsumeStatus.LIMIT_EXCEEDED
                    pipeline.multi()
                    if code != expected_value:
                        pipeline.set(attempts_redis_key, attempts + 1, ex=ttl)
                        result = HashConsumeStatus.MISMATCH
                    else:
                        pipeline.delete(code_redis_key, attempts_redis_key)
                        result = HashConsumeStatus.ACCEPTED
                    self._call(pipeline.execute)
                    return result
            except WatchError:
                continue
            except RedisError as exc:
                raise StorageUnavailableError("Redis storage is unavailable") from exc
        raise StorageUnavailableError("Redis storage changed too quickly while consuming a hash")

    def queue_push(self, key: str, value: str) -> None:
        self._call(self._client.rpush, self._key(key), value)

    def queue_pop(self, key: str) -> str | None:
        return self._call(self._client.lpop, self._key(key))

    def queue_remove(self, key: str, value: str) -> bool:
        return bool(self._call(self._client.lrem, self._key(key), 0, value))

    def queue_length(self, key: str) -> int:
        return int(self._call(self._client.llen, self._key(key)))

    def queue_clear(self, key: str) -> bool:
        return bool(self._call(self._client.delete, self._key(key)))

    def queue_items(self, key: str) -> list[str]:
        return list(self._call(self._client.lrange, self._key(key), 0, -1))
