from __future__ import annotations

"""Redis 键构造器（单一事实来源）。

项目约束：Redis 仅保存带 TTL 的临时安全态。所有键统一采用
`{module}:{purpose}:{id}` 的内部形态，前缀（默认 `listingo`）由
`RedisStorage._key` 在写入时统一追加，因此这里的构造器只产出"内部键"，
不负责前缀。集中到本模块可避免散落的 f-string 产生命名漂移。

命名约定（详见 docs/REDIS_KEYS.md）：
    listingo:rate:{identity}:{window_id}       固定窗口限流计数
    listingo:nonce:{sha256}                    Nonce 防重放
    listingo:login_failure:{ip}:{window_id}    登录失败计数
    listingo:login_block:{ip}                  登录封禁标记
    listingo:sms:daily:{identity}              短信日限额滑动窗口
    listingo:sms:cooldown:{identity}           短信发送冷却
    listingo:sms:code:{identity}               短信验证码哈希
    listingo:sms:attempts:{identity}           短信验证码尝试计数
"""


def rate_limit_key(identity: str, window_id: int) -> str:
    return f"rate:{identity}:{window_id}"


def nonce_key(nonce_hash: str) -> str:
    return f"nonce:{nonce_hash}"


def login_failure_key(ip: str, window_id: int) -> str:
    return f"login_failure:{ip}:{window_id}"


def login_block_key(ip: str) -> str:
    return f"login_block:{ip}"


def sms_daily_key(identity: str) -> str:
    return f"sms:daily:{identity}"


def sms_cooldown_key(identity: str) -> str:
    return f"sms:cooldown:{identity}"


def sms_code_key(identity: str) -> str:
    return f"sms:code:{identity}"


def sms_attempts_key(identity: str) -> str:
    return f"sms:attempts:{identity}"


def cache_key(domain: str, identifier: str) -> str:
    """Reusable derived-state cache keys (providers, prompts, plans, OCR results)."""
    return f"cache:{domain}:{identifier}"


def cache_version_key(domain: str) -> str:
    """Generation counter used to invalidate a whole cache domain without SCAN."""
    return f"cache:{domain}:version"


def session_cache_key(token_hash: str) -> str:
    return f"session:{token_hash}"


def batch_status_key(batch_id: str) -> str:
    return f"batch:status:{batch_id}"


def queue_key(kind: str) -> str:
    """Runtime FIFO queues rebuilt from PostgreSQL job facts."""
    return f"queue:{kind}"


def lock_key(scope: str, identifier: str) -> str:
    return f"lock:{scope}:{identifier}"


def metric_daily_key(day: str, name: str) -> str:
    return f"metric:daily:{day}:{name}"


def sensitive_word_meta_key() -> str:
    return "sensitive:words:meta"


def sensitive_word_snapshot_key() -> str:
    return "sensitive:words:snapshot"
