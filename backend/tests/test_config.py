from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.responses import Response

from backend.app.config import Settings
from backend.app.main import create_app
from backend.app.services.auth import issue_session
from backend.app.services.sms import send_aliyun_sms


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_env_files_document_every_configured_variable() -> None:
    for filename in (".env.local", ".env.production"):
        lines = (PROJECT_ROOT / filename).read_text(encoding="utf-8").splitlines()
        assignments = [index for index, line in enumerate(lines) if line and not line.startswith("#")]
        assert assignments
        for index in assignments:
            assert lines[index - 1].startswith("#"), f"{filename}:{index + 1} lacks a comment"
            assert "使用位置" in lines[index - 1], f"{filename}:{index + 1} lacks a usage-location comment"


def test_settings_selects_env_file_from_environment(tmp_path: Path, monkeypatch) -> None:
    env_file = tmp_path / "selected.env"
    env_file.write_text(
        "\n".join(
            [
                "LISTINGO_DATABASE_URL=postgresql://postgres:secret@localhost:5432/listingo",
                "LISTINGO_CORS_ORIGINS=https://api.example.com, https://console.example.com",
                "LISTINGO_DEBUG_SMS_CODE=135790",
                "LISTINGO_SMS_TIMEOUT_SECONDS=17.5",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("LISTINGO_ENV_FILE", str(env_file))

    settings = Settings()

    assert settings.cors_origin_list == ["https://api.example.com", "https://console.example.com"]
    assert settings.debug_sms_code == "135790"
    assert settings.sms_timeout_seconds == 17.5


def test_default_and_production_env_files_keep_expected_modes(monkeypatch) -> None:
    for name in ("LISTINGO_ENV_FILE", "LISTINGO_COOKIE_SECURE", "LISTINGO_DEBUG_SMS_CODE", "LISTINGO_GLOBAL_DRY_RUN"):
        monkeypatch.delenv(name, raising=False)

    local = Settings()
    assert local.cookie_secure is False
    assert local.debug_sms_code == "246810"

    monkeypatch.setenv("LISTINGO_ENV_FILE", ".env.production")
    production = Settings()
    assert production.cookie_secure is True
    assert production.debug_sms_code in (None, "")
    assert production.global_dry_run is False


def test_settings_validate_and_normalize_redis_configuration() -> None:
    database_url = "postgresql://postgres:secret@localhost:5432/listingo"
    settings = Settings(
        database_url=database_url,
        redis_url="rediss://default:secret@redis.example.com:6380/2",
        redis_key_prefix=" Listingo_prod ",
        _env_file=None,
    )

    assert settings.storage_backend == "redis"
    assert settings.redis_url == "rediss://default:secret@redis.example.com:6380/2"
    assert settings.redis_key_prefix == "Listingo_prod"

    with pytest.raises(ValidationError, match="LISTINGO_REDIS_URL"):
        Settings(database_url=database_url, redis_url="mysql://redis.invalid:6379/0", _env_file=None)

    with pytest.raises(ValidationError, match="LISTINGO_REDIS_KEY_PREFIX"):
        Settings(database_url=database_url, redis_key_prefix="bad prefix", _env_file=None)


def test_settings_require_postgresql_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LISTINGO_DATABASE_URL", raising=False)
    with pytest.raises(ValidationError, match="LISTINGO_DATABASE_URL"):
        Settings(_env_file=None)

    with pytest.raises(ValidationError, match="LISTINGO_DATABASE_URL"):
        Settings(database_url="sqlite:///data/listingo.sqlite3", _env_file=None)

    settings = Settings(
        database_url="postgresql+psycopg2://postgres:secret@localhost:5432/listingo",
        _env_file=None,
    )
    assert settings.resolved_database_url == "postgresql://postgres:secret@localhost:5432/listingo"


def test_cors_middleware_uses_settings_origins(
    tmp_path: Path,
    postgres_database_url: str,
) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        database_url=postgres_database_url,
        cors_origins="https://console.example.com",
        storage_backend="memory",
        _env_file=None,
    )
    client = TestClient(create_app(settings))

    response = client.options(
        "/api/v1/health",
        headers={"Origin": "https://console.example.com", "Access-Control-Request-Method": "GET"},
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://console.example.com"


def test_issue_session_uses_configured_ttl_and_secure_cookie() -> None:
    settings = Settings(
        database_url="postgresql://postgres:secret@localhost:5432/listingo",
        session_ttl_seconds=120,
        refresh_ttl_seconds=600,
        cookie_secure=True,
        _env_file=None,
    )
    request = SimpleNamespace(
        headers={},
        client=None,
        app=SimpleNamespace(state=SimpleNamespace(settings=settings)),
    )
    response = Response()
    user = SimpleNamespace(id="user-id", last_login_at=None)
    session = SimpleNamespace(add=lambda _item: None)

    issue_session(session, request, response, user)
    cookies = response.headers.getlist("set-cookie")

    assert any("listingo_session=" in cookie and "Max-Age=120" in cookie and "Secure" in cookie for cookie in cookies)
    assert any("listingo_refresh=" in cookie and "Max-Age=600" in cookie and "Secure" in cookie for cookie in cookies)


def test_aliyun_sms_uses_configured_http_timeout(monkeypatch) -> None:
    captured: dict[str, float] = {}

    class FakeAsyncClient:
        def __init__(self, *, timeout: float) -> None:
            captured["timeout"] = timeout

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def get(self, *_args: object, **_kwargs: object) -> object:
            return SimpleNamespace(
                raise_for_status=lambda: None,
                json=lambda: {"Code": "OK", "BizId": "test-biz-id"},
            )

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    result = asyncio.run(
        send_aliyun_sms(
            access_key_id="key-id",
            access_key_secret="key-secret",
            region_id="cn-hangzhou",
            phone="13800138000",
            sign_name="Listingo",
            template_code="SMS-TEST",
            code="123456",
            timeout_seconds=17.5,
        )
    )

    assert result == "test-biz-id"
    assert captured["timeout"] == 17.5
