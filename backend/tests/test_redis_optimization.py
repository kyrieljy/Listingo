from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from fakeredis import FakeRedis

from backend.app.config import Settings
from backend.app.core.rate_limit import NONCE_TTL_SECONDS, NonceStatus, RateLimitService, create_rate_limiter
from backend.app.core.storage.base import HashConsumeStatus, StorageItem
from backend.app.core.storage.keys import (
    login_block_key,
    login_failure_key,
    nonce_key,
    rate_limit_key,
    sms_attempts_key,
    sms_code_key,
    sms_cooldown_key,
    sms_daily_key,
)
from backend.app.core.storage.redis import RedisStorage
from redis.connection import ConnectionPool
from backend.app.services import sms as sms_module


def _settings(**overrides: object) -> Settings:
    # 必须提供合法的 postgresql URL 以通过字段校验（不建立真实连接）。
    base = {
        "database_url": "postgresql://localhost/listingo_test",
        "storage_backend": "memory",
        "_env_file": None,
    }
    base.update(overrides)  # type: ignore[arg-type]
    return Settings(**base)  # type: ignore[arg-type]


def test_settings_propagate_to_rate_limiter() -> None:
    settings = _settings(redis_nonce_ttl_seconds=120, redis_login_block_seconds=90)
    limiter = create_rate_limiter(settings)
    try:
        assert limiter.nonce_ttl_seconds == 120
        assert limiter.login_block_seconds == 90

        # 缺省 ttl 走可配置规范值（120），接受。
        assert limiter.consume_nonce("1234567890abcdef").status is NonceStatus.ACCEPTED
        # 显式 ttl 与规范不一致（60 != 120）-> 非法 Nonce。
        assert limiter.consume_nonce("1234567890abcdef", ttl=60).status is NonceStatus.INVALID

        # 封禁时长走可配置值（90），且不影响默认 60s 失败窗口下的 5 次阈值。
        for _ in range(5):
            limiter.record_failure_and_block("203.0.113.9")
        assert limiter.is_ip_blocked("203.0.113.9")
        assert limiter.block_ttl_seconds("203.0.113.9") == 90
    finally:
        limiter.close()


def test_defaults_preserve_historical_behavior() -> None:
    # 不覆盖任何 Redis 配置时，行为与历史一致（nonce 60 / block 1800）。
    settings = _settings()
    limiter = create_rate_limiter(settings)
    try:
        assert limiter.nonce_ttl_seconds == NONCE_TTL_SECONDS == 60
        assert limiter.login_block_seconds == 1800
        assert limiter.consume_nonce("1234567890abcdef").status is NonceStatus.ACCEPTED
        assert limiter.consume_nonce("1234567890abcdef", ttl=61).status is NonceStatus.INVALID
    finally:
        limiter.close()


def test_key_builders_match_convention() -> None:
    assert rate_limit_key("ip", 7) == "rate:ip:7"
    assert nonce_key("abc") == "nonce:abc"
    assert login_failure_key("1.2.3.4", 9) == "login_failure:1.2.3.4:9"
    assert login_block_key("1.2.3.4") == "login_block:1.2.3.4"
    assert sms_daily_key("id") == "sms:daily:id"
    assert sms_cooldown_key("id") == "sms:cooldown:id"
    assert sms_code_key("id") == "sms:code:id"
    assert sms_attempts_key("id") == "sms:attempts:id"


def test_redis_key_prefix_isolation() -> None:
    storage = RedisStorage(
        url="redis://localhost:6379/0",
        key_prefix="listingo",
        client=FakeRedis(decode_responses=True),
    )
    try:
        assert storage._key("rate:x:1") == "listingo:rate:x:1"
        assert storage._key(nonce_key("abc")) == "listingo:nonce:abc"
    finally:
        storage.close()


def test_redis_storage_builds_connection_pool_with_max_connections() -> None:
    storage = RedisStorage(
        url="redis://localhost:6379/0",
        max_connections=7,
        health_check_interval_seconds=3,
    )
    try:
        pool = storage.client.connection_pool
        # 显式连接池上限生效；health_check_interval 透传给底层连接（redis-py 不暴露为池属性）。
        assert isinstance(pool, ConnectionPool)
        assert pool.max_connections == 7
    finally:
        storage.close()


def test_sms_reserve_send_quota_uses_configurable_daily_window() -> None:
    storage = MagicMock()
    storage.reserve_sliding_window.return_value = True
    config = SimpleNamespace(daily_limit_per_phone=3, cooldown_seconds=0)

    token = sms_module._reserve_send_quota(
        storage,
        "id",
        config,
        bypass_rate_limit=False,
        daily_window_seconds=123,
    )

    call_args = storage.reserve_sliding_window.call_args
    assert call_args.args[0] == sms_daily_key("id")
    assert call_args.args[1] == token
    assert call_args.args[2] == 3
    assert call_args.args[3] == 123


def test_verify_sms_code_uses_configurable_max_attempts_and_keys() -> None:
    settings = _settings(redis_sms_max_attempts=9)
    storage = MagicMock()
    storage.get.return_value = StorageItem(value="h", expires_in_seconds=60)
    captured: dict[str, object] = {}

    def fake_consume(code_key: str, attempts_key: str, _expected: str, **kwargs: object) -> HashConsumeStatus:
        captured["code_key"] = code_key
        captured["attempts_key"] = attempts_key
        captured["max_attempts"] = kwargs["max_attempts"]
        return HashConsumeStatus.ACCEPTED

    storage.consume_hash_once.side_effect = fake_consume
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                rate_limiter=SimpleNamespace(storage=storage),
                settings=settings,
            )
        )
    )

    sms_module.verify_sms_code(request, phone="+8613800138000", purpose="login", code="123456")

    identity = sms_module._sms_identity(sms_module.normalize_phone("+8613800138000"), "login")
    assert captured["max_attempts"] == 9
    assert captured["code_key"] == sms_code_key(identity)
    assert captured["attempts_key"] == sms_attempts_key(identity)
    storage.get.assert_called_once_with(sms_code_key(identity))
