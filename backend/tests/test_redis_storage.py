from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from fakeredis import FakeRedis
import pytest
from redis.exceptions import ConnectionError

from backend.app.core.storage.base import HashConsumeStatus, StorageUnavailableError
from backend.app.core.storage.memory import MemoryStorage
from backend.app.core.storage.keys import sensitive_word_meta_key, sensitive_word_snapshot_key
from backend.app.core.storage.redis import RedisStorage


@pytest.fixture()
def fake_redis() -> FakeRedis:
    return FakeRedis(decode_responses=True)


@pytest.fixture()
def storage(fake_redis: FakeRedis) -> RedisStorage:
    return RedisStorage(
        url="redis://localhost:6379/0",
        key_prefix="listingo-test",
        client=fake_redis,
    )


def test_redis_storage_uses_prefix_ttl_and_atomic_increment(storage: RedisStorage, fake_redis: FakeRedis) -> None:
    first = storage.incr("rate:counter", 60)
    second = storage.incr("rate:counter", 60)

    assert (first.value, second.value) == (1, 2)
    assert 1 <= first.expires_in_seconds <= 60
    assert fake_redis.get("listingo-test:rate:counter") == "2"
    assert fake_redis.ttl("listingo-test:rate:counter") > 0


def test_redis_persistent_many_is_atomic_without_ttl(storage: RedisStorage, fake_redis: FakeRedis) -> None:
    storage.set_persistent_many(
        {
            sensitive_word_meta_key(): '{"digest":"same"}',
            sensitive_word_snapshot_key(): '{"words":[]}',
        }
    )

    assert fake_redis.ttl(f"listingo-test:{sensitive_word_meta_key()}") == -1
    assert fake_redis.ttl(f"listingo-test:{sensitive_word_snapshot_key()}") == -1
    assert storage.get(sensitive_word_meta_key()).expires_in_seconds is None


def test_memory_persistent_many_ignores_ttl_lru_and_capacity() -> None:
    memory = MemoryStorage(max_size=2, start_cleanup_thread=False)

    memory.set_persistent_many(
        {
            sensitive_word_meta_key(): "meta",
            sensitive_word_snapshot_key(): "snapshot",
        }
    )

    assert memory.setex("derived-a", "value", 60).success
    assert memory.setex("derived-b", "value", 60).success
    assert memory.setex("derived-c", "value", 60).success
    assert memory.get("derived-a") is None
    assert memory.get("derived-b") is not None
    assert memory.get("derived-c") is not None

    assert memory.get(sensitive_word_meta_key()).expires_in_seconds is None
    assert memory.exists(sensitive_word_snapshot_key())


def test_redis_set_if_absent_wins_once_under_concurrency(storage: RedisStorage) -> None:
    def consume(index: int) -> bool:
        return storage.set_if_absent("nonce:same", str(index), 60).success

    with ThreadPoolExecutor(max_workers=12) as executor:
        results = list(executor.map(consume, range(12)))

    assert sum(results) == 1


def test_redis_sliding_window_reserves_and_releases(storage: RedisStorage) -> None:
    assert storage.reserve_sliding_window("sms:daily", "token-1", 1, 86_400)
    assert not storage.reserve_sliding_window("sms:daily", "token-2", 1, 86_400)

    assert storage.release_sliding_window("sms:daily", "token-1")
    assert storage.reserve_sliding_window("sms:daily", "token-3", 1, 86_400)


def test_redis_sliding_window_retains_reservations_for_full_window(
    storage: RedisStorage,
    fake_redis: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock_values = [(1_000, 0), (1_002, 0), (1_000 + 86_401, 0)]
    monkeypatch.setattr(fake_redis, "time", lambda: clock_values.pop(0))

    assert storage.reserve_sliding_window("sms:daily", "token-1", 1, 86_400)
    assert not storage.reserve_sliding_window("sms:daily", "token-2", 1, 86_400)
    assert storage.reserve_sliding_window("sms:daily", "token-3", 1, 86_400)


def test_redis_delete_if_equal_only_removes_matching_value(storage: RedisStorage) -> None:
    storage.setex("cooldown", "token-1", 60)

    assert not storage.delete_if_equal("cooldown", "token-2")
    assert storage.delete_if_equal("cooldown", "token-1")
    assert storage.get("cooldown") is None


def test_redis_consumes_hash_once_and_enforces_attempts(storage: RedisStorage) -> None:
    storage.setex("code", "expected-hash", 60)

    assert storage.consume_hash_once("code", "attempts", "wrong-hash", 60, 5) is HashConsumeStatus.MISMATCH
    assert storage.get("attempts") is not None
    assert storage.consume_hash_once("code", "attempts", "expected-hash", 60, 5) is HashConsumeStatus.ACCEPTED
    assert storage.get("code") is None
    assert storage.get("attempts") is None


def test_redis_hash_rejects_after_five_wrong_attempts(storage: RedisStorage) -> None:
    storage.setex("code", "expected-hash", 60)

    statuses = [storage.consume_hash_once("code", "attempts", "wrong", 60, 5) for _ in range(5)]
    assert set(statuses) == {HashConsumeStatus.MISMATCH}
    assert storage.consume_hash_once("code", "attempts", "expected-hash", 60, 5) is HashConsumeStatus.LIMIT_EXCEEDED


def test_redis_errors_are_controlled(
    storage: RedisStorage,
    fake_redis: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable(*_args: object, **_kwargs: object) -> None:
        raise ConnectionError("redis is offline")

    monkeypatch.setattr(fake_redis, "get", unavailable)

    with pytest.raises(StorageUnavailableError):
        storage.get("missing")


def test_redis_cleanup_and_close_are_safe(storage: RedisStorage) -> None:
    storage.start_cleanup_thread()
    assert storage.cleanup_expired() == 0
    storage.close()
