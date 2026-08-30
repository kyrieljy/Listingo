from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock

from sqlalchemy import select

from backend.app.models import BatchJob, SmsConfig, User
from backend.app.services import notifications as notifications_svc
from backend.app.services import sms as sms_svc
from backend.app.services.notifications import (
    build_task_result_title,
    create_batch_result_notification_once,
    create_job_result_notification_once,
    notify_task_completion_external,
)
from backend.app.services import generation_queues as genq_svc
from backend.app.services.generation_queues import GenerationQueueScheduler


def _configure_debug_sms(client, *, cooldown_seconds: int = 0, code_ttl_seconds: int = 300) -> None:
    session_factory = client.app.state.session_factory
    with session_factory() as session:
        config = session.query(SmsConfig).first()
        config.enabled = True
        config.debug_mode = True
        config.cooldown_seconds = cooldown_seconds
        config.code_ttl_seconds = code_ttl_seconds
        config.daily_limit_per_phone = 10
        session.commit()
    client.app.state.settings.debug_sms_code = "654321"


def _make_user(client, *, feishu_webhook: str | None = None) -> str:
    suffix = uuid.uuid4().hex[:12]
    user_id = f"tn-{suffix}"
    with client.app.state.session_factory() as session:
        session.add(
            User(
                id=user_id,
                phone=f"139{suffix}",
                username=user_id,
                display_name="Notify User",
                uid=user_id,
                feishu_webhook=feishu_webhook,
            )
        )
        session.commit()
    return user_id


def _set_sms_config(session_factory, cipher, *, debug_mode=False, notify_template_code=None):
    with session_factory() as session:
        config = session.query(SmsConfig).order_by(SmsConfig.created_at.asc()).first()
        if config is None:
            config = SmsConfig()
            session.add(config)
        config.enabled = True
        config.debug_mode = debug_mode
        config.notify_template_code = notify_template_code or ""
        config.access_key_id = "AKID_TEST"
        config.sign_name = "Listingo"
        config.region_id = "cn-hangzhou"
        config.encrypted_access_key_secret = cipher.encrypt("secret-value")
        session.commit()


# --------------------------------------------------------------------------- #
# 1. Single source of truth for completion copy                               #
# --------------------------------------------------------------------------- #
def test_build_task_result_title_matrix():
    assert build_task_result_title(category="generation", status="succeeded") == "生图任务已完成"
    assert build_task_result_title(category="video", status="succeeded") == "视频任务已完成"
    assert build_task_result_title(category="generation", status="partial_failed") == "生图任务部分完成"
    assert build_task_result_title(category="generation", status="failed") == "生图任务生成失败"
    assert build_task_result_title(category="batch", business_type="aplus", status="succeeded") == "A+详情批量任务已完成"
    assert build_task_result_title(category="batch", business_type="suite", status="succeeded") == "商品套图批量任务已完成"
    assert build_task_result_title(category="batch", business_type="aplus", status="failed") == "A+详情批量任务生成失败"


def test_in_app_notification_reuses_shared_title(client):
    user_id = _make_user(client)
    job_id = "job-shared-title"
    with client.app.state.session_factory() as session:
        note = create_job_result_notification_once(
            session, user_id, category="generation", job_id=job_id, status="succeeded", dry_run=True
        )
        session.commit()
        assert note.title == build_task_result_title(category="generation", status="succeeded")

        # Idempotent: same deterministic id on repeat.
        again = create_job_result_notification_once(
            session, user_id, category="generation", job_id=job_id, status="succeeded", dry_run=True
        )
        assert again.id == note.id


def test_batch_in_app_notification_reuses_shared_title(client):
    user_id = _make_user(client)
    batch_id = "batch-shared-title"
    with client.app.state.session_factory() as session:
        note = create_batch_result_notification_once(
            session,
            user_id,
            batch_id=batch_id,
            business_type="aplus",
            status="succeeded",
            completed_count=3,
            failed_count=0,
            total_count=3,
        )
        session.commit()
        assert note.title == build_task_result_title(category="batch", business_type="aplus", status="succeeded")


# --------------------------------------------------------------------------- #
# 2. Feishu webhook payload                                                   #
# --------------------------------------------------------------------------- #
def test_post_feishu_webhook_payload(monkeypatch):
    captured = {}

    class _Resp:
        def raise_for_status(self):
            return None

    class _Client:
        def __init__(self, *args, **kwargs):
            captured["args"] = (args, kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, json=None, **kwargs):
            captured["url"] = url
            captured["json"] = json
            return _Resp()

    monkeypatch.setattr(notifications_svc.httpx, "AsyncClient", _Client)
    asyncio.run(notifications_svc._post_feishu_webhook("https://hook.test/x", "生图任务已完成", timeout=5.0))
    assert captured["url"] == "https://hook.test/x"
    assert captured["json"] == {"msg_type": "text", "content": {"text": "生图任务已完成"}}


# --------------------------------------------------------------------------- #
# 3. SMS notify: quota isolation + template param                             #
# --------------------------------------------------------------------------- #
def test_send_sms_notification_skips_debug_mode(client, monkeypatch):
    cipher = client.app.state.cipher
    fake_send = AsyncMock(return_value="biz-1")
    monkeypatch.setattr(sms_svc, "send_aliyun_sms", fake_send)
    _set_sms_config(client.app.state.session_factory, cipher, debug_mode=True, notify_template_code="SMS_NTF")

    with client.app.state.session_factory() as session:
        asyncio.run(
            sms_svc.send_sms_notification(
                session, client.app.state.settings, cipher, phone="13800138000", text="生图任务已完成"
            )
        )
    fake_send.assert_not_called()


def test_send_sms_notification_skips_missing_template(client, monkeypatch):
    cipher = client.app.state.cipher
    fake_send = AsyncMock(return_value="biz-1")
    monkeypatch.setattr(sms_svc, "send_aliyun_sms", fake_send)
    _set_sms_config(client.app.state.session_factory, cipher, debug_mode=False, notify_template_code=None)

    with client.app.state.session_factory() as session:
        asyncio.run(
            sms_svc.send_sms_notification(
                session, client.app.state.settings, cipher, phone="13800138000", text="生图任务已完成"
            )
        )
    fake_send.assert_not_called()


def test_send_sms_notification_sends_with_content_param(client, monkeypatch):
    cipher = client.app.state.cipher
    fake_send = AsyncMock(return_value="biz-1")
    monkeypatch.setattr(sms_svc, "send_aliyun_sms", fake_send)
    _set_sms_config(client.app.state.session_factory, cipher, debug_mode=False, notify_template_code="SMS_NTF")

    with client.app.state.session_factory() as session:
        asyncio.run(
            sms_svc.send_sms_notification(
                session, client.app.state.settings, cipher, phone="13800138000", text="生图任务已完成"
            )
        )
    fake_send.assert_called_once()
    kwargs = fake_send.call_args.kwargs
    assert kwargs["template_code"] == "SMS_NTF"
    assert kwargs["template_param"] == {"content": "生图任务已完成"}
    assert kwargs["code"] == "生图任务已完成"


# --------------------------------------------------------------------------- #
# 4. External notify dispatch (Feishu + SMS)                                  #
# --------------------------------------------------------------------------- #
def test_external_notify_feishu_and_sms(client, monkeypatch):
    cipher = client.app.state.cipher
    feishu_mock = AsyncMock()
    sms_mock = AsyncMock()
    monkeypatch.setattr(notifications_svc, "_post_feishu_webhook", feishu_mock)
    monkeypatch.setattr(sms_svc, "send_sms_notification", sms_mock)
    user_id = _make_user(client, feishu_webhook="https://open.feishu.cn/open-apis/bot/v2/hook/abc")

    with client.app.state.session_factory() as session:
        user = session.get(User, user_id)
        asyncio.run(
            notify_task_completion_external(
                session, client.app.state.settings, cipher, user=user, category="generation", status="succeeded"
            )
        )
    feishu_mock.assert_awaited_once_with(
        "https://open.feishu.cn/open-apis/bot/v2/hook/abc",
        "生图任务已完成",
        timeout=client.app.state.settings.sms_timeout_seconds,
    )
    sms_mock.assert_awaited_once()


def test_external_notify_skips_feishu_when_unset(client, monkeypatch):
    cipher = client.app.state.cipher
    feishu_mock = AsyncMock()
    sms_mock = AsyncMock()
    monkeypatch.setattr(notifications_svc, "_post_feishu_webhook", feishu_mock)
    monkeypatch.setattr(sms_svc, "send_sms_notification", sms_mock)
    user_id = _make_user(client, feishu_webhook=None)

    with client.app.state.session_factory() as session:
        user = session.get(User, user_id)
        asyncio.run(
            notify_task_completion_external(
                session, client.app.state.settings, cipher, user=user, category="video", status="failed"
            )
        )
    feishu_mock.assert_not_awaited()
    sms_mock.assert_awaited_once()


def test_external_notify_feishu_failure_does_not_block_sms(client, monkeypatch):
    cipher = client.app.state.cipher
    feishu_mock = AsyncMock(side_effect=RuntimeError("webhook down"))
    sms_mock = AsyncMock()
    monkeypatch.setattr(notifications_svc, "_post_feishu_webhook", feishu_mock)
    monkeypatch.setattr(sms_svc, "send_sms_notification", sms_mock)
    user_id = _make_user(client, feishu_webhook="https://open.feishu.cn/open-apis/bot/v2/hook/abc")

    with client.app.state.session_factory() as session:
        user = session.get(User, user_id)
        # Must not raise even though Feishu failed.
        asyncio.run(
            notify_task_completion_external(
                session, client.app.state.settings, cipher, user=user, category="generation", status="succeeded"
            )
        )
    sms_mock.assert_awaited_once()


# --------------------------------------------------------------------------- #
# 5. Profile API persists Feishu webhook; /auth/me echoes it                 #
# --------------------------------------------------------------------------- #
def test_profile_update_persists_feishu_webhook(client):
    _configure_debug_sms(client)
    phone = "13800138066"
    sent = client.post("/api/v1/auth/sms/send", json={"phone": phone, "purpose": "login"})
    login = client.post("/api/v1/auth/sms/login", json={"phone": phone, "code": sent.json()["debug_code"]})
    assert login.status_code == 200

    webhook = "https://open.feishu.cn/open-apis/bot/v2/hook/valid123"
    patch = client.patch("/api/v1/account/profile", json={"feishu_webhook": webhook})
    assert patch.status_code == 200
    assert patch.json()["user"]["feishu_webhook"] == webhook
    assert patch.json()["user"]["feishu_webhook_configured"] is True

    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["user"]["feishu_webhook"] == webhook
    assert me.json()["user"]["feishu_webhook_configured"] is True

    # Clearing the webhook unsets the configured flag.
    cleared = client.patch("/api/v1/account/profile", json={"feishu_webhook": ""})
    assert cleared.status_code == 200
    assert cleared.json()["user"]["feishu_webhook"] == ""
    assert cleared.json()["user"]["feishu_webhook_configured"] is False


# --------------------------------------------------------------------------- #
# 6. Worker scheduling units                                                  #
# --------------------------------------------------------------------------- #
def test_schedule_external_notification_delegates_generation(client, monkeypatch):
    scheduler: GenerationQueueScheduler = client.app.state.generation_queue_scheduler
    notify_mock = AsyncMock()
    monkeypatch.setattr(scheduler, "_notify_external_async", notify_mock)

    async def _drive():
        scheduler._schedule_external_notification(category="generation", job_id="gen-xyz", business_type=None)
        await asyncio.sleep(0.01)

    asyncio.run(_drive())
    notify_mock.assert_awaited_once_with(category="generation", job_id="gen-xyz", business_type=None)


def test_schedule_external_notification_delegates_batch(client, monkeypatch):
    scheduler: GenerationQueueScheduler = client.app.state.generation_queue_scheduler
    notify_mock = AsyncMock()
    monkeypatch.setattr(scheduler, "_notify_external_async", notify_mock)

    async def _drive():
        scheduler._schedule_external_notification(category="batch", job_id="batch-xyz", business_type="aplus")
        await asyncio.sleep(0.01)

    asyncio.run(_drive())
    notify_mock.assert_awaited_once_with(category="batch", job_id="batch-xyz", business_type="aplus")


def test_notify_external_async_batch_dispatches(client, monkeypatch):
    scheduler: GenerationQueueScheduler = client.app.state.generation_queue_scheduler
    ext_mock = AsyncMock()
    # generation_queues imports notify_task_completion_external via `from ... import`,
    # so the local binding must be patched on that module, not on notifications.
    monkeypatch.setattr(genq_svc, "notify_task_completion_external", ext_mock)

    user_id = _make_user(client)
    batch_id = "batch-tick-ext"
    with client.app.state.session_factory() as session:
        session.add(
            BatchJob(
                id=batch_id,
                user_id=user_id,
                business_type="suite",
                status="partial_failed",
                total_count=3,
                completed_count=2,
                failed_count=1,
            )
        )
        session.commit()

    asyncio.run(scheduler._notify_external_async(category="batch", job_id=batch_id, business_type="suite"))
    ext_mock.assert_awaited_once()
    kwargs = ext_mock.call_args.kwargs
    assert kwargs["category"] == "batch"
    assert kwargs["business_type"] == "suite"
    assert kwargs["status"] == "partial_failed"


def test_notify_external_async_skips_non_terminal_batch(client, monkeypatch):
    scheduler: GenerationQueueScheduler = client.app.state.generation_queue_scheduler
    ext_mock = AsyncMock()
    monkeypatch.setattr(genq_svc, "notify_task_completion_external", ext_mock)

    user_id = _make_user(client)
    batch_id = "batch-running"
    with client.app.state.session_factory() as session:
        session.add(
            BatchJob(
                id=batch_id,
                user_id=user_id,
                business_type="suite",
                status="running",
                total_count=3,
                completed_count=0,
                failed_count=0,
            )
        )
        session.commit()

    asyncio.run(scheduler._notify_external_async(category="batch", job_id=batch_id, business_type="suite"))
    ext_mock.assert_not_awaited()
