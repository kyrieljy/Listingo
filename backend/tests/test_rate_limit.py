from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading

import pytest
from fakeredis import FakeRedis
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.core import rate_limit as rate_limit_module
from backend.app.core.rate_limit import (
    NONCE_TTL_SECONDS,
    NonceStatus,
    RateLimitService,
    create_rate_limiter,
    rate_limit_headers,
)
from backend.app.core.storage.memory import MemoryStorage
from backend.app.core.storage.redis import RedisStorage
from backend.app.core.storage.base import StorageUnavailableError
from backend.app.main import create_app


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{(tmp_path / 'data' / 'test.sqlite3').as_posix()}",
        testing=True,
        storage_backend="memory",
        _env_file=None,
    )


def app_client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings))


def redis_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    fake_redis = FakeRedis(decode_responses=True)

    def fake_factory(**_kwargs: object) -> RedisStorage:
        return RedisStorage(
            url="redis://localhost:6379/0",
            key_prefix="listingo-test",
            client=fake_redis,
        )

    monkeypatch.setattr(rate_limit_module, "RedisStorage", fake_factory)
    settings = Settings(
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{(tmp_path / 'data' / 'test.sqlite3').as_posix()}",
        testing=True,
        storage_backend="redis",
        redis_startup_timeout_seconds=0.5,
        _env_file=None,
    )
    return TestClient(create_app(settings))


def test_memory_storage_lru_expiry_and_nonce_capacity() -> None:
    now = 100.0

    def clock() -> float:
        return now

    storage = MemoryStorage(max_size=1, start_cleanup_thread=False, clock=clock)
    assert storage.set_if_absent("nonce:a", "1", NONCE_TTL_SECONDS).success
    assert not storage.set_if_absent("nonce:b", "1", NONCE_TTL_SECONDS).success

    now += NONCE_TTL_SECONDS
    assert storage.cleanup_expired() == 1
    assert storage.set_if_absent("nonce:b", "1", NONCE_TTL_SECONDS).success

    bounded = MemoryStorage(max_size=3, start_cleanup_thread=False, clock=clock)
    bounded.setex("old", "1", 30)
    bounded.setex("recent", "1", 30)
    bounded.incr("counter", 30)
    assert bounded.size == 3
    assert bounded.get("old") is not None
    bounded.incr("new-counter", 30)
    assert bounded.get("recent") is None
    assert bounded.get("old") is not None


def test_set_if_absent_is_atomic_under_concurrency() -> None:
    storage = MemoryStorage(max_size=10, start_cleanup_thread=False)

    def consume(index: int) -> bool:
        return storage.set_if_absent("nonce:same", str(index), NONCE_TTL_SECONDS).success

    with ThreadPoolExecutor(max_workers=12) as executor:
        results = list(executor.map(consume, range(12)))

    assert sum(results) == 1


def test_cleanup_thread_stops_on_close() -> None:
    storage = MemoryStorage(cleanup_interval_seconds=1, start_cleanup_thread=True)
    thread = storage._cleanup_thread
    assert thread is not None and thread.is_alive()

    storage.close()

    assert not thread.is_alive()


def test_rate_limit_headers_and_nonce_statuses() -> None:
    limiter = RateLimitService(MemoryStorage(start_cleanup_thread=False))
    results = [limiter.consume_rate_limit("generation", 3, 60) for _ in range(4)]

    assert [result.allowed for result in results] == [True, True, True, False]
    assert results[-1].remaining == 0
    assert 1 <= results[-1].reset_in_seconds <= 60
    assert rate_limit_headers(results[-1]) == {
        "X-RateLimit-Limit": "3",
        "X-RateLimit-Remaining": "0",
        "X-RateLimit-Reset": str(results[-1].reset_in_seconds),
    }

    assert limiter.consume_nonce("1234567890abcdef").status is NonceStatus.ACCEPTED
    assert limiter.consume_nonce("1234567890abcdef").status is NonceStatus.DUPLICATE
    assert limiter.consume_nonce("short").status is NonceStatus.INVALID
    assert limiter.consume_nonce("1234567890abcdef", ttl=61).status is NonceStatus.INVALID


def test_login_failures_block_ip_for_1800_seconds() -> None:
    limiter = RateLimitService(MemoryStorage(start_cleanup_thread=False))

    failures = [limiter.record_failure_and_block("203.0.113.8") for _ in range(4)]
    assert failures == [False, False, False, False]
    assert not limiter.is_ip_blocked("203.0.113.8")

    assert limiter.record_failure_and_block("203.0.113.8")
    assert limiter.is_ip_blocked("203.0.113.8")
    assert limiter.block_ttl_seconds("203.0.113.8") == NONCE_TTL_SECONDS * 30
    assert not limiter.is_ip_blocked("203.0.113.9")


def test_generation_and_video_share_one_rate_limit_window(client: TestClient) -> None:
    suite_payload = {
        "asset_ids": ["missing-asset"],
        "platform": "Amazon",
        "market": "美国",
        "language": "English",
        "aspect_ratio": "1:1",
        "selling_points": "双层保温",
        "dry_run": True,
    }
    video_payload = {
        **suite_payload,
        "country": "美国",
        "video_types": ["UGC 种草"],
    }

    for _ in range(10):
        assert client.post("/api/v1/generation-jobs", json=suite_payload).status_code == 422
        assert client.post("/api/v1/video-jobs", json=video_payload).status_code == 422

    limited = client.post("/api/v1/generation-jobs", json=suite_payload)

    assert limited.status_code == 429
    assert limited.headers["X-RateLimit-Limit"] == "20"
    assert limited.headers["X-RateLimit-Remaining"] == "0"
    assert 1 <= int(limited.headers["X-RateLimit-Reset"]) <= 60


def test_five_password_failures_block_subsequent_requests(client: TestClient) -> None:
    payload = {"identifier": "rate-limit-user", "password": "wrong-password"}
    headers = {"X-Forwarded-For": "198.51.100.7"}

    statuses = [client.post("/api/v1/auth/password/login", json=payload, headers=headers).status_code for _ in range(5)]

    assert statuses == [401, 401, 401, 401, 403]
    assert client.get("/api/v1/health", headers=headers).status_code == 403
    assert client.get("/api/v1/health").status_code == 200
    assert client.app.state.rate_limiter.block_ttl_seconds("198.51.100.7") == 1800
    blocked = client.get("/api/v1/health", headers={**headers, "Origin": "http://localhost:5173"})
    assert blocked.status_code == 403
    assert blocked.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_redis_backend_preserves_generation_nonce_and_block_behavior(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with redis_app(tmp_path, monkeypatch) as client:
        suite_payload = {
            "asset_ids": ["missing-asset"],
            "platform": "Amazon",
            "market": "美国",
            "language": "English",
            "aspect_ratio": "1:1",
            "selling_points": "双层保温",
            "dry_run": True,
        }
        for _ in range(20):
            assert client.post("/api/v1/generation-jobs", json=suite_payload).status_code == 422
        limited = client.post("/api/v1/generation-jobs", json=suite_payload)
        assert limited.status_code == 429
        assert limited.headers["X-RateLimit-Limit"] == "20"

        accepted = client.post(
            "/api/v1/account/password",
            headers={"X-Request-Nonce": "1234567890abcdef"},
            json={"current_password": "old", "next_password": "new-password"},
        )
        duplicate = client.post(
            "/api/v1/account/password",
            headers={"X-Request-Nonce": "1234567890abcdef"},
            json={"current_password": "old", "next_password": "new-password"},
        )
        assert (accepted.status_code, duplicate.status_code) == (200, 409)

        login_headers = {"X-Forwarded-For": "198.51.100.8"}
        login = {"identifier": "redis-user", "password": "wrong-password"}
        statuses = [
            client.post("/api/v1/auth/password/login", json=login, headers=login_headers).status_code
            for _ in range(5)
        ]
        assert statuses == [401, 401, 401, 401, 403]
        assert client.get("/api/v1/health", headers=login_headers).status_code == 403
        assert client.app.state.rate_limiter.block_ttl_seconds("198.51.100.8") == 1800


def test_sensitive_endpoints_require_and_reject_nonce(client: TestClient) -> None:
    missing = client.post("/api/v1/account/password", json={"current_password": "old", "next_password": "new-password"})
    invalid = client.post(
        "/api/v1/account/password",
        headers={"X-Request-Nonce": "too-short"},
        json={"current_password": "old", "next_password": "new-password"},
    )
    accepted = client.post(
        "/api/v1/account/password",
        headers={"X-Request-Nonce": "1234567890abcdef"},
        json={"current_password": "old", "next_password": "new-password"},
    )
    duplicate = client.post(
        "/api/v1/account/password",
        headers={"X-Request-Nonce": "1234567890abcdef"},
        json={"current_password": "old", "next_password": "new-password"},
    )

    assert missing.status_code == 400
    assert invalid.status_code == 400
    assert accepted.status_code == 200
    assert duplicate.status_code == 409


def test_full_nonce_capacity_returns_429(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    settings.rate_limit_max_size = 1
    with app_client(settings) as client:
        first = client.post(
            "/api/v1/account/password",
            headers={"X-Request-Nonce": "1234567890abcdef"},
            json={"current_password": "old", "next_password": "new-password"},
        )
        second = client.post(
            "/api/v1/account/password",
            headers={"X-Request-Nonce": "abcdefghijklmnop"},
            json={"current_password": "old", "next_password": "new-password"},
        )

        assert first.status_code == 200
        assert second.status_code == 429


def test_web_concurrency_above_one_fails_outside_testing(monkeypatch, tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    settings.testing = False
    monkeypatch.setenv("WEB_CONCURRENCY", "2")

    with pytest.raises(RuntimeError, match="memory rate limiting"):
        create_app(settings)


def test_redis_backend_allows_multiple_workers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WEB_CONCURRENCY", "4")

    with redis_app(tmp_path, monkeypatch) as client:
        assert client.get("/api/v1/health").status_code == 200


def test_redis_startup_failure_does_not_fallback_to_memory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_redis = FakeRedis(decode_responses=True)
    failing_storage = RedisStorage(
        url="redis://localhost:6379/0",
        key_prefix="listingo-test",
        client=fake_redis,
    )

    def unavailable(*_args: object, **_kwargs: object) -> None:
        raise StorageUnavailableError("redis is offline")

    monkeypatch.setattr(failing_storage, "ping", unavailable)
    monkeypatch.setattr(rate_limit_module, "RedisStorage", lambda **_kwargs: failing_storage)
    settings = Settings(
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{(tmp_path / 'data' / 'test.sqlite3').as_posix()}",
        testing=False,
        storage_backend="redis",
        redis_startup_timeout_seconds=0.5,
        _env_file=None,
    )

    with pytest.raises(RuntimeError, match="Redis is unavailable"):
        with TestClient(create_app(settings)):
            pass


def test_storage_unavailable_returns_503(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def unavailable(*_args: object, **_kwargs: object) -> bool:
        raise StorageUnavailableError("redis is offline")

    monkeypatch.setattr(client.app.state.rate_limiter, "is_ip_blocked", unavailable)

    response = client.get("/api/v1/health")

    assert response.status_code == 503


def test_non_testing_lifespan_starts_and_stops_cleanup(caplog, tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    settings.testing = False
    app = create_app(settings)
    with caplog.at_level("WARNING", logger="backend.app.main"):
        with TestClient(app) as client:
            storage = client.app.state.rate_limiter.storage
            thread = storage._cleanup_thread
            assert thread is not None and thread.is_alive()
            assert "WARNING: Rate limiting is running in MEMORY mode." in caplog.text

        assert thread is not None and not thread.is_alive()


def test_rate_limiter_uses_configured_capacity(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    settings.rate_limit_max_size = 2
    limiter = create_rate_limiter(settings)

    try:
        assert limiter.storage.get("missing") is None
        assert limiter.consume_nonce("1234567890abcdef").status is NonceStatus.ACCEPTED
        assert limiter.consume_nonce("abcdefghijklmnop").status is NonceStatus.ACCEPTED
        assert limiter.consume_nonce("qrstuvwxyz123456").status is NonceStatus.CAPACITY_EXCEEDED
    finally:
        limiter.close()
