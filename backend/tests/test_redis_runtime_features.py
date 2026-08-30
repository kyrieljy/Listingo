from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path
from unittest.mock import MagicMock

from fakeredis import FakeRedis
from fastapi import HTTPException
from PIL import Image
from sqlalchemy import select

from backend.app.core.runtime import RuntimeStateService, RuntimeTTLs
from backend.app.core.storage.base import StorageUnavailableError
from backend.app.core.storage.keys import (
    cache_version_key,
    lock_key,
    metric_daily_key,
    queue_key,
    session_cache_key,
)
from backend.app.core.storage.memory import MemoryStorage
from backend.app.core.storage.redis import RedisStorage
from backend.app.models import (
    BatchJob,
    PaymentOrder,
    PlanQuotaRule,
    Provider,
    SmsConfig,
    SubscriptionPlan,
    User,
    UserSession,
    utcnow,
)
from backend.app.services.auth import SESSION_COOKIE, hash_token
from backend.app.services.batch_jobs import (
    cached_batch_job_payload,
    invalidate_batch_status,
)
from backend.app.services.image_text_edit import detect_text_lines_with_status
from backend.app.services.metrics import increment_analytics_event_counters, realtime_metrics
from backend.app.services.provider_routing import cached_provider_by_code
from backend.app.services.runtime_cache import (
    active_prompt_version_id,
    active_workflow_version_id,
)
from backend.app.services.subscriptions import (
    mock_pay_order,
    reserve_quota,
)


class ManualClock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_runtime_json_ttl_lock_and_counter_in_memory() -> None:
    clock = ManualClock()
    storage = MemoryStorage(max_size=20, start_cleanup_thread=False, clock=clock)
    runtime = RuntimeStateService(storage)

    runtime.set_json(cache_version_key("test"), {"ok": True}, 5)
    assert runtime.get_json(cache_version_key("test")) == {"ok": True}
    clock.advance(5)
    assert runtime.get_json(cache_version_key("test")) is None

    key = lock_key("quota", "user:image:2026-08")
    token = runtime.acquire_lock(key, 5)
    assert token is not None
    assert runtime.acquire_lock(key, 5) is None
    assert runtime.release_lock(key, "not-owner") is False
    assert runtime.release_lock(key, token) is True

    counter_key = metric_daily_key("20260823", "total")
    assert runtime.increment(counter_key, 10) == 1
    assert runtime.increment(counter_key, 10) == 2

    storage.close()


def test_runtime_redis_storage_and_none_cache_entries() -> None:
    fake_redis = FakeRedis(decode_responses=True)
    storage = RedisStorage(url="redis://localhost:6379/0", client=fake_redis)
    runtime = RuntimeStateService(storage, ttls=RuntimeTTLs(cache=60))

    runtime.set_json(cache_version_key("redis-test"), {"value": 1}, 60)
    assert fake_redis.ttl("listingo:cache:redis-test:version") > 0
    assert runtime.get_json(cache_version_key("redis-test")) == {"value": 1}

    producer_calls = 0

    def produce() -> str | None:
        nonlocal producer_calls
        producer_calls += 1
        return None

    assert runtime.cached_versioned("provider", "missing", produce) is None
    assert runtime.cached_versioned("provider", "missing", produce) is None
    assert producer_calls == 1
    assert runtime.invalidate("provider", 60) == 2

    storage.close()


def test_runtime_optional_paths_fail_open_while_locks_fail_closed() -> None:
    storage = MagicMock()
    storage.get.side_effect = StorageUnavailableError("offline")
    storage.incr.side_effect = StorageUnavailableError("offline")
    storage.set_if_absent.side_effect = StorageUnavailableError("offline")
    runtime = RuntimeStateService(storage)

    assert runtime.cached_versioned("provider", "missing", lambda: "postgres") == "postgres"
    runtime.increment_best_effort(metric_daily_key("20260823", "total"), 10)

    try:
        runtime.acquire_lock(lock_key("order-pay", "order"), 10)
    except StorageUnavailableError:
        pass
    else:
        raise AssertionError("Lock acquisition must fail closed")


def test_admin_updates_invalidate_provider_prompt_workflow_and_plan_caches(client) -> None:
    providers = client.get("/api/v1/admin/providers").json()
    provider_payload = next(item for item in providers if item["code"] == "atlas-gpt-image-2-generate")
    with client.app.state.session_factory() as session:
        first = cached_provider_by_code(session, provider_payload["code"], client.app.state.runtime_state)
        assert first is not None
    provider_version = client.app.state.runtime_state.cache_version(
        "provider", client.app.state.runtime_state.ttls.cache_version
    )

    response = client.patch(
        f"/api/v1/admin/providers/{provider_payload['id']}",
        json={"label": "Atlas cached label"},
    )
    assert response.status_code == 200, response.text
    invalidated_provider_version = client.app.state.runtime_state.cache_version(
        "provider", client.app.state.runtime_state.ttls.cache_version
    )
    assert invalidated_provider_version != provider_version
    with client.app.state.session_factory() as session:
        fresh = cached_provider_by_code(session, provider_payload["code"], client.app.state.runtime_state)
        assert fresh is not None and fresh.label == "Atlas cached label"

    prompt = client.get("/api/v1/admin/prompts").json()[0]
    version = client.post(
        f"/api/v1/admin/prompts/{prompt['id']}/versions",
        json={"content": "# cached prompt version", "change_note": "redis cache test"},
    ).json()
    with client.app.state.session_factory() as session:
        assert active_prompt_version_id(session, prompt["code"]) == prompt["active_version_id"]
    activated = client.post(f"/api/v1/admin/prompts/{prompt['id']}/versions/{version['id']}/activate")
    assert activated.status_code == 200
    with client.app.state.session_factory() as session:
        assert active_prompt_version_id(session, prompt["code"]) == version["id"]

    workflow = client.get("/api/v1/admin/workflows").json()[0]
    workflow_detail = client.get(f"/api/v1/admin/workflows/{workflow['id']}").json()
    graph = workflow_detail["versions"][0]["graph"]
    workflow_version = client.post(
        f"/api/v1/admin/workflows/{workflow['id']}/versions",
        json={"graph": graph, "change_note": "redis cache test"},
    ).json()
    with client.app.state.session_factory() as session:
        assert active_workflow_version_id(session, workflow["code"]) == workflow["active_version_id"]
    activated_workflow = client.post(
        f"/api/v1/admin/workflows/{workflow['id']}/versions/{workflow_version['id']}/activate"
    )
    assert activated_workflow.status_code == 200
    with client.app.state.session_factory() as session:
        assert active_workflow_version_id(session, workflow["code"]) == workflow_version["id"]

    plans = client.get("/api/v1/admin/subscription-plans").json()
    plan = next(item for item in plans if item["code"] == "standard")
    updated = client.patch(
        f"/api/v1/admin/subscription-plans/{plan['id']}",
        json={"description": "Redis cache invalidated plan"},
    )
    assert updated.status_code == 200, updated.text
    refreshed = client.get("/api/v1/admin/subscription-plans").json()
    refreshed_plan = next(item for item in refreshed if item["code"] == "standard")
    assert refreshed_plan["description"] == "Redis cache invalidated plan"


def test_session_cache_hit_still_checks_user_and_logout_invalidates(client) -> None:
    with client.app.state.session_factory() as session:
        config = session.scalar(select(SmsConfig).limit(1))
        assert config is not None
        config.enabled = True
        config.debug_mode = True
        config.cooldown_seconds = 0
        config.daily_limit_per_phone = 10
    client.app.state.settings.debug_sms_code = "654321"
    phone = "13800138999"
    assert client.post("/api/v1/auth/sms/send", json={"phone": phone, "purpose": "register"}).status_code == 200
    login = client.post(
        "/api/v1/auth/sms/login",
        json={"phone": phone, "mode": "register", "code": "654321"},
    )
    assert login.status_code == 200, login.text

    assert client.get("/api/v1/auth/me").status_code == 200
    token = client.cookies.get(SESSION_COOKIE)
    assert token is not None
    key = session_cache_key(hash_token(token))
    assert client.app.state.runtime_state.get_json(key) is not None

    with client.app.state.session_factory() as session:
        auth_session = session.scalar(select(UserSession).where(UserSession.session_token_hash == hash_token(token)))
        assert auth_session is not None
        user = session.get(User, auth_session.user_id)
        assert user is not None
        user.status = "disabled"
        session.commit()
    assert client.get("/api/v1/auth/me").status_code == 403

    with client.app.state.session_factory() as session:
        user = session.scalar(select(User).where(User.phone == phone))
        assert user is not None
        user.status = "active"
        session.commit()
    assert client.post("/api/v1/auth/logout").status_code == 200
    assert client.app.state.runtime_state.get_json(key) is None


def test_batch_snapshot_and_generation_queue_claim_lock(client, monkeypatch) -> None:
    with client.app.state.session_factory() as session:
        batch = BatchJob(business_type="suite", user_id=None)
        session.add(batch)
        session.commit()

        first = cached_batch_job_payload(session, batch, runtime=client.app.state.runtime_state)
        assert first["status"] == "queued"
        batch.status = "running"
        session.commit()
        stale = cached_batch_job_payload(session, batch, runtime=client.app.state.runtime_state)
        assert stale["status"] == "queued"
        invalidate_batch_status(batch.id, client.app.state.runtime_state)
        fresh = cached_batch_job_payload(session, batch, runtime=client.app.state.runtime_state)
        assert fresh["status"] == "running"

    scheduler = client.app.state.generation_queue_scheduler
    claim_calls = 0

    def claim_once(task_id: str) -> bool:
        nonlocal claim_calls
        claim_calls += 1
        return False

    monkeypatch.setattr(scheduler, "_claim_batch_item", claim_once)
    scheduler.storage.queue_push(queue_key("generation"), "batch_item:locked")

    async def stop_on_sleep(_: float) -> None:
        scheduler._stopping.set()

    monkeypatch.setattr(scheduler, "_sleep", stop_on_sleep)
    claim_key = lock_key("generation-queue", "generation")
    token = client.app.state.runtime_state.acquire_lock(claim_key, 10)
    assert token is not None
    scheduler._stopping.clear()
    asyncio.run(scheduler._run_loop("generation"))
    assert claim_calls == 0
    assert scheduler.queue_length("generation") == 1
    assert client.app.state.runtime_state.release_lock(claim_key, token)
    scheduler._stopping.clear()
    asyncio.run(scheduler._run_loop("generation"))
    assert claim_calls == 1
    assert scheduler.queue_length("generation") == 0


def test_quota_and_order_locks_preserve_payment_idempotency(client) -> None:
    runtime = client.app.state.runtime_state
    with client.app.state.session_factory() as session:
        user = session.scalar(select(User).where(User.username == "admin"))
        assert user is not None
        plan = session.scalar(select(SubscriptionPlan).where(SubscriptionPlan.code == "standard"))
        assert plan is not None
        assert session.scalar(select(PlanQuotaRule).where(PlanQuotaRule.plan_id == plan.id).limit(1)) is not None

        quota_key = lock_key("quota", f"{user.id}:image_generation:{utcnow().strftime('%Y-%m')}")
        quota_token = runtime.acquire_lock(quota_key, 10)
        assert quota_token is not None
        try:
            reserve_quota(
                session,
                user,
                action_key="image_generation",
                amount=1,
                ref_type="redis-test",
                ref_id="quota-1",
            )
        except HTTPException as exc:
            assert exc.status_code == 409
        else:
            raise AssertionError("A held quota lock must produce 409")
        finally:
            assert runtime.release_lock(quota_key, quota_token)
        session.rollback()

        pending = PaymentOrder(
            order_no="REDIS-PENDING",
            user_id=user.id,
            plan_id=plan.id,
            billing_cycle="monthly",
            amount_cents=3000,
            status="pending",
            expires_at=utcnow() + timedelta(minutes=30),
            snapshot_json="{}",
        )
        paid = PaymentOrder(
            order_no="REDIS-PAID",
            user_id=user.id,
            plan_id=plan.id,
            billing_cycle="monthly",
            amount_cents=3000,
            status="paid",
            expires_at=utcnow() + timedelta(minutes=30),
            snapshot_json="{}",
        )
        session.add_all([pending, paid])
        session.commit()

        pending_key = lock_key("order-pay", pending.id)
        pending_token = runtime.acquire_lock(pending_key, 10)
        assert pending_token is not None
        try:
            mock_pay_order(session, user, pending.id)
        except HTTPException as exc:
            assert exc.status_code == 409
        else:
            raise AssertionError("A held payment lock must produce 409")
        finally:
            assert runtime.release_lock(pending_key, pending_token)
        session.rollback()

        paid_key = lock_key("order-pay", paid.id)
        paid_token = runtime.acquire_lock(paid_key, 10)
        assert paid_token is not None
        assert mock_pay_order(session, user, paid.id).status == "paid"
        assert runtime.release_lock(paid_key, paid_token)
        session.commit()


def test_realtime_metrics_counters_and_ocr_result_cache(client, tmp_path, monkeypatch) -> None:
    for event_type in ("view", "click"):
        response = client.post(
            "/api/v1/analytics/events",
            json={
                "session_id": "redis-runtime-test",
                "event_name": f"redis_{event_type}",
                "event_type": event_type,
                "business_type": "suite",
            },
        )
        assert response.status_code == 201, response.text

    ops = client.get("/api/v1/admin/ops-monitoring").json()
    assert ops["realtime_metrics"]["total"] == 2
    assert ops["realtime_metrics"]["by_event_type"] == {"click": 1, "view": 1}
    assert next(card for card in ops["summary_cards"] if card["key"] == "realtime_events")["numeric"] == 2

    image_path = tmp_path / "ocr-cache.png"
    Image.new("RGB", (120, 80), "#ffffff").save(image_path)
    engine_calls = 0
    variant_calls = 0

    def fake_engine(_path: str) -> list[object]:
        nonlocal engine_calls
        engine_calls += 1
        return []

    def fake_variants(_path: Path, _settings) -> list[tuple[str, float, bool]]:
        nonlocal variant_calls
        variant_calls += 1
        return [(str(image_path), 1.0, False)]

    def fake_rows(_raw, _scale, _settings, _language, _size) -> list[dict]:
        return [{"text": "hello", "confidence": 0.99, "bbox": {"x": 10, "y": 10, "width": 40, "height": 12}}]

    monkeypatch.setattr("backend.app.services.image_text_edit._load_ocr_engine", lambda _settings: fake_engine)
    monkeypatch.setattr("backend.app.services.image_text_edit._prepare_ocr_variants", fake_variants)
    monkeypatch.setattr("backend.app.services.image_text_edit._parse_ocr_rows", fake_rows)

    first = detect_text_lines_with_status(image_path, client.app.state.settings, "en")
    second = detect_text_lines_with_status(image_path, client.app.state.settings, "en")
    assert [line.text for line in first.lines] == ["hello"]
    assert second.lines == first.lines
    assert (engine_calls, variant_calls) == (1, 1)

    changed_settings = client.app.state.settings.model_copy(update={"ocr_text_score_threshold": 0.7})
    changed = detect_text_lines_with_status(image_path, changed_settings, "en")
    assert changed.lines == first.lines
    assert (engine_calls, variant_calls) == (2, 2)
