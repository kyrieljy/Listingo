from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _settings_env_file() -> Path:
    configured = os.getenv("LISTINGO_ENV_FILE", "").strip()
    if not configured:
        return PROJECT_ROOT / ".env.local"
    path = Path(configured).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


class _EnvFileUnset:
    pass


_ENV_FILE_UNSET = _EnvFileUnset()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LISTINGO_", extra="ignore")

    data_dir: Path = PROJECT_ROOT / "data"
    database_url: str = ""
    database_pool_size: int = Field(default=5, ge=1)
    database_max_overflow: int = Field(default=10, ge=0)
    database_pool_recycle_seconds: int = Field(default=1800, ge=30)
    testing: bool = False
    global_dry_run: bool = True
    public_asset_base_url: str = ""
    cors_origins: str = "http://127.0.0.1:5173,http://localhost:5173"
    storage_backend: Literal["redis", "memory"] = "redis"
    redis_url: str = "redis://127.0.0.1:6379/0"
    redis_key_prefix: str = "listingo"
    redis_connect_timeout_seconds: float = Field(default=2.0, ge=0.1)
    redis_socket_timeout_seconds: float = Field(default=2.0, ge=0.1)
    redis_startup_timeout_seconds: float = Field(default=5.0, ge=0.5)
    # 安全态 Redis 的差异化 TTL / 阈值（运维可调，无需改代码）。
    redis_nonce_ttl_seconds: int = Field(default=60, ge=1)
    redis_login_fail_window_seconds: int = Field(default=60, ge=1)
    redis_login_block_seconds: int = Field(default=1800, ge=1)
    redis_sms_daily_window_seconds: int = Field(default=24 * 60 * 60, ge=1)
    redis_sms_max_attempts: int = Field(default=5, ge=1)
    # 连接池调优：上限与空闲健康检查间隔。
    redis_max_connections: int = Field(default=50, ge=1)
    redis_health_check_interval_seconds: int = Field(default=30, ge=0)
    # Redis 派生态 TTL：热点缓存 / 会话元数据 / 批量状态 / 锁 / 实时计数 / OCR 结果。
    redis_cache_ttl_seconds: int = Field(default=300, ge=1)
    redis_cache_version_ttl_seconds: int = Field(default=7 * 24 * 60 * 60, ge=60)
    redis_session_cache_ttl_seconds: int = Field(default=300, ge=1)
    redis_batch_status_ttl_seconds: int = Field(default=3, ge=1)
    redis_lock_ttl_seconds: int = Field(default=30, ge=1)
    redis_metric_ttl_seconds: int = Field(default=2 * 24 * 60 * 60, ge=1)
    redis_ocr_cache_ttl_seconds: int = Field(default=3600, ge=1)
    rate_limit_max_size: int = Field(default=10_000, ge=1)
    rate_limit_cleanup_interval_seconds: int = Field(default=30, ge=1)
    max_upload_bytes: int = 15 * 1024 * 1024
    session_ttl_seconds: int = Field(default=60 * 60 * 8, ge=60)
    refresh_ttl_seconds: int = Field(default=60 * 60 * 24 * 30, ge=60)
    cookie_secure: bool = False
    debug_sms_code: str | None = None
    sms_timeout_seconds: float = Field(default=15, ge=0.1)
    max_job_concurrency: int = Field(default=4, ge=1, le=8)
    max_batch_tasks: int = Field(default=100, ge=1, le=100)
    max_batch_item_assets: int = Field(default=6, ge=1, le=12)
    max_active_batch_items: int = Field(default=1, ge=1, le=8)
    max_provider_concurrency: int = Field(default=4, ge=1, le=16)
    ocr_engine: str = "rapidocr"
    ocr_primary_model: str = "PP-OCRv5"
    ocr_fallback_model: str = "PP-OCRv6"
    ocr_device: str = "cpu"
    ocr_text_score_threshold: float = Field(default=0.62, ge=0, le=1)
    ocr_box_score_threshold: float = Field(default=0.6, ge=0, le=1)
    ocr_short_text_score_threshold: float = Field(default=0.86, ge=0, le=1)
    ocr_min_box_width: int = Field(default=5, ge=0)
    ocr_min_box_height: int = Field(default=5, ge=0)
    ocr_min_box_area: int = Field(default=40, ge=0)
    ocr_filter_isolated_cjk: bool = True
    ocr_filter_watermark_text: bool = True
    ocr_use_enhanced_variants: bool = False

    def __init__(
        self,
        _env_file: Path | str | None | _EnvFileUnset = _ENV_FILE_UNSET,
        **values: Any,
    ) -> None:
        selected_env_file = _settings_env_file() if isinstance(_env_file, _EnvFileUnset) else _env_file
        super().__init__(_env_file=selected_env_file, **values)

    @field_validator("database_url")
    @classmethod
    def _validate_database_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {"postgresql", "postgresql+psycopg2"} or not parsed.netloc or not parsed.path.strip("/"):
            raise ValueError(
                "LISTINGO_DATABASE_URL must be a postgresql:// or postgresql+psycopg2:// URL "
                "with a host and database name"
            )
        return value

    @field_validator("redis_url")
    @classmethod
    def _validate_redis_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {"redis", "rediss"} or not parsed.netloc:
            raise ValueError("LISTINGO_REDIS_URL must be a redis:// or rediss:// URL")
        return value

    @field_validator("redis_key_prefix")
    @classmethod
    def _validate_redis_key_prefix(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or any(not char.isalnum() and char not in {".", "_", "-"} for char in normalized):
            raise ValueError("LISTINGO_REDIS_KEY_PREFIX may only contain letters, numbers, dot, underscore, and hyphen")
        return normalized

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def resolved_database_url(self) -> str:
        # SQLAlchemy 2.0 selects psycopg2 as the default synchronous PostgreSQL driver.
        return self.database_url.replace("postgresql+psycopg2://", "postgresql://", 1)

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def results_dir(self) -> Path:
        return self.data_dir / "results"

    @property
    def exports_dir(self) -> Path:
        return self.data_dir / "exports"

    @property
    def secret_key_path(self) -> Path:
        return self.data_dir / ".secret_key"

    def ensure_directories(self) -> None:
        for directory in (self.data_dir, self.uploads_dir, self.results_dir, self.exports_dir):
            directory.mkdir(parents=True, exist_ok=True)
