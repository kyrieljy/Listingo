from __future__ import annotations

import asyncio
import inspect
import uuid
from unittest.mock import AsyncMock

import httpx
import pytest

from backend.app.models import SmsConfig, User
from backend.app.services import notifications as notifications_svc
from backend.app.services import sms as sms_svc
from backend.app.services.notifications import (
    FEISHU_TEST_TEXT,
    FeishuWebhookError,
    _post_feishu_webhook,
    notify_task_completion_external,
)


def _configure_debug_sms(client) -> None:
    with client.app.state.session_factory() as session:
        config = session.query(SmsConfig).first()
        config.enabled = True
        config.debug_mode = True
        config.cooldown_seconds = 0
        config.code_ttl_seconds = 300
        config.daily_limit_per_phone = 10
        session.commit()
    client.app.state.settings.debug_sms_code = "654321"


def _login(client, phone: str) -> None:
    sent = client.post("/api/v1/auth/sms/send", json={"phone": phone, "purpose": "login"})
    login = client.post("/api/v1/auth/sms/login", json={"phone": phone, "code": sent.json()["debug_code"]})
    assert login.status_code == 200


def _make_user(client, *, feishu_webhook: str | None = None) -> str:
    suffix = uuid.uuid4().hex[:12]
    user_id = f"fw-{suffix}"
    with client.app.state.session_factory() as session:
        session.add(
            User(
                id=user_id,
                phone=f"139{suffix}",
                username=user_id,
                display_name="Feishu User",
                uid=user_id,
                feishu_webhook=feishu_webhook,
            )
        )
        session.commit()
    return user_id


def _install_client(
    monkeypatch,
    *,
    status_code: int = 200,
    payload: dict | None = None,
    exc: Exception | None = None,
) -> dict:
    """Patch httpx.AsyncClient and return a dict capturing the outbound POST."""
    captured: dict = {}

    class _Response:
        def __init__(self) -> None:
            self.status_code = status_code

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                request = httpx.Request("POST", captured.get("url", "https://hook.test/x"))
                raise httpx.HTTPStatusError("bad status", request=request, response=self)

        def json(self) -> dict:
            if payload is None:
                raise ValueError("no json body")
            return payload

    class _Client:
        def __init__(self, *args, **kwargs) -> None:
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info) -> bool:
            return False

        async def post(self, url, json=None, **kwargs):
            captured["url"] = url
            captured["json"] = json
            if exc is not None:
                raise exc
            return _Response()

    monkeypatch.setattr(notifications_svc.httpx, "AsyncClient", _Client)
    return captured


# --------------------------------------------------------------------------- #
# 1. Test-push endpoint                                                        #
# --------------------------------------------------------------------------- #
def test_test_endpoint_pushes_probe_text(client, monkeypatch):
    _configure_debug_sms(client)
    _login(client, "13800138071")
    captured = _install_client(monkeypatch, payload={"code": 0, "msg": "success"})

    response = client.post(
        "/api/v1/account/feishu-webhook/test",
        json={"webhook": "https://open.feishu.cn/open-apis/bot/v2/hook/xyz"},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert captured["url"] == "https://open.feishu.cn/open-apis/bot/v2/hook/xyz"
    assert captured["json"] == {"msg_type": "text", "content": {"text": "设计就上Listingo"}}
    assert captured["json"]["content"]["text"] == FEISHU_TEST_TEXT


def test_test_endpoint_rejects_empty_webhook(client, monkeypatch):
    _configure_debug_sms(client)
    _login(client, "13800138072")
    captured = _install_client(monkeypatch)

    response = client.post("/api/v1/account/feishu-webhook/test", json={"webhook": ""})

    assert response.status_code == 400
    assert response.json()["detail"] == "请先填写飞书 Webhook 地址"
    assert "url" not in captured


def test_test_endpoint_falls_back_to_saved_webhook(client, monkeypatch):
    _configure_debug_sms(client)
    _login(client, "13800138073")
    saved = "https://open.feishu.cn/open-apis/bot/v2/hook/saved"
    client.patch("/api/v1/account/profile", json={"feishu_webhook": saved})
    captured = _install_client(monkeypatch)

    response = client.post("/api/v1/account/feishu-webhook/test", json={"webhook": ""})

    assert response.status_code == 200
    assert captured["url"] == saved


def test_test_endpoint_declares_auth_dependency():
    """Guard the auth dependency.

    It cannot be asserted at runtime here: the test harness runs with
    `settings.testing=True`, and `current_user_from_request` falls back to an
    existing user via `_testing_user`, so unauthenticated calls still return 200.
    """
    from backend.app.api import auth as auth_api

    source = inspect.getsource(auth_api.test_feishu_webhook)
    assert "Depends(get_current_user)" in source


# --------------------------------------------------------------------------- #
# 2. Feishu-level error detection (HTTP 200 + code != 0)                       #
# --------------------------------------------------------------------------- #
def test_test_endpoint_reports_feishu_code_error(client, monkeypatch):
    _configure_debug_sms(client)
    _login(client, "13800138074")
    _install_client(monkeypatch, payload={"code": 19001, "msg": "param invalid: incoming webhook access denied"})

    response = client.post(
        "/api/v1/account/feishu-webhook/test",
        json={"webhook": "https://open.feishu.cn/open-apis/bot/v2/hook/bad"},
    )

    assert response.status_code == 502
    assert "param invalid" in response.json()["detail"]


def test_test_endpoint_reports_http_error(client, monkeypatch):
    _configure_debug_sms(client)
    _login(client, "13800138075")
    _install_client(monkeypatch, status_code=404)

    response = client.post(
        "/api/v1/account/feishu-webhook/test",
        json={"webhook": "https://open.feishu.cn/open-apis/bot/v2/hook/missing"},
    )

    assert response.status_code == 502
    assert "404" in response.json()["detail"]


def test_post_feishu_webhook_treats_code_zero_as_success(monkeypatch):
    _install_client(monkeypatch, payload={"code": 0})
    asyncio.run(_post_feishu_webhook("https://hook.test/x", "生图任务已完成", timeout=1.0))


def test_post_feishu_webhook_raises_on_nonzero_code(monkeypatch):
    _install_client(monkeypatch, payload={"code": 9499, "msg": "bad request"})
    with pytest.raises(FeishuWebhookError, match="bad request"):
        asyncio.run(_post_feishu_webhook("https://hook.test/x", "生图任务已完成", timeout=1.0))


def test_post_feishu_webhook_translates_timeout(monkeypatch):
    _install_client(monkeypatch, exc=httpx.ConnectTimeout("too slow"))
    with pytest.raises(FeishuWebhookError, match="超时"):
        asyncio.run(_post_feishu_webhook("https://hook.test/x", "生图任务已完成", timeout=1.0))


def test_post_feishu_webhook_tolerates_response_without_json(monkeypatch):
    """The worker's own response mocks may not expose json(); must not blow up."""
    captured = _install_client(monkeypatch)
    asyncio.run(_post_feishu_webhook("https://hook.test/x", "生图任务已完成", timeout=1.0))
    assert captured["url"] == "https://hook.test/x"


# --------------------------------------------------------------------------- #
# 3. Regression: the worker notify path must still never raise                #
# --------------------------------------------------------------------------- #
def test_worker_notify_swallows_feishu_code_error(client, monkeypatch):
    """016 contract: a Feishu-level failure must not break task-completion notify."""
    cipher = client.app.state.cipher
    sms_mock = AsyncMock()
    monkeypatch.setattr(sms_svc, "send_sms_notification", sms_mock)
    _install_client(monkeypatch, payload={"code": 19001, "msg": "denied"})
    user_id = _make_user(client, feishu_webhook="https://open.feishu.cn/open-apis/bot/v2/hook/abc")

    with client.app.state.session_factory() as session:
        user = session.get(User, user_id)
        asyncio.run(
            notify_task_completion_external(
                session,
                client.app.state.settings,
                cipher,
                user=user,
                category="generation",
                status="succeeded",
            )
        )
    sms_mock.assert_awaited_once()
