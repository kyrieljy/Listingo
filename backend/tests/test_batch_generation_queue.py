from __future__ import annotations

import asyncio
from io import BytesIO
import json

from PIL import Image
from sqlalchemy import select

from backend.app.core.storage.base import StorageUnavailableError
from backend.app.core.storage.keys import queue_key
from backend.app.models import BatchItem, BatchJob, GenerationJob, Notification
from backend.app.services.generation_queue_service import batch_item_token


def make_png() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (180, 180), "#e8eef5").save(buffer, format="PNG")
    return buffer.getvalue()


def upload_asset(client) -> str:
    response = client.post(
        "/api/v1/assets",
        files={"file": ("queue-product.png", make_png(), "image/png")},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def batch_payload(asset_id: str, count: int = 2) -> dict:
    return {
        "business_type": "suite",
        "global_params": {
            "platform": "Amazon",
            "market": "美国",
            "language": "English",
            "aspect_ratio": "1:1",
            "count": 7,
            "dry_run": True,
        },
        "items": [
            {
                "asset_ids": [asset_id],
                "name": f"Queue item {index}",
                "selling_points": "轻量耐用",
            }
            for index in range(count)
        ],
    }


def scheduler(client):
    return client.app.state.generation_queue_scheduler


def drain_generation(client) -> None:
    while scheduler(client).queue_length("generation"):
        asyncio.run(scheduler(client).tick("generation"))


def test_batch_creation_only_writes_database_and_generation_buffer(client) -> None:
    asset_id = upload_asset(client)

    response = client.post("/api/v1/batch-jobs", json=batch_payload(asset_id))

    assert response.status_code == 201, response.text
    batch = response.json()
    assert batch["status"] == "queued"
    assert all(item["status"] == "queued" for item in batch["items"])
    assert scheduler(client).queue_items("generation") == [
        batch_item_token(item["id"]) for item in batch["items"]
    ]
    with client.app.state.session_factory() as session:
        batch_row = session.get(BatchJob, batch["id"])
        assert batch_row.status == "queued"
        for item in batch_row.items:
            assert item.status == "queued"
            assert session.get(GenerationJob, item.generation_job_id).status == "queued"
        notifications = session.scalars(
            select(Notification).where(Notification.user_id == batch_row.user_id)
        ).all()
        assert notifications == []


def test_cancel_removes_every_queued_batch_token(client) -> None:
    asset_id = upload_asset(client)
    created = client.post("/api/v1/batch-jobs", json=batch_payload(asset_id))
    assert created.status_code == 201, created.text
    batch_id = created.json()["id"]

    response = client.post(f"/api/v1/batch-jobs/{batch_id}/cancel")

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "cancelled"
    assert scheduler(client).queue_length("generation") == 0
    with client.app.state.session_factory() as session:
        batch = session.get(BatchJob, batch_id)
        assert batch.status == "cancelled"
        for item in batch.items:
            assert item.status == "cancelled"
            assert session.get(GenerationJob, item.generation_job_id).status == "cancelled"


def test_cancel_after_worker_claim_returns_409_and_keeps_buffer(client) -> None:
    asset_id = upload_asset(client)
    created = client.post("/api/v1/batch-jobs", json=batch_payload(asset_id))
    assert created.status_code == 201, created.text
    batch_id = created.json()["id"]

    first_item_id = created.json()["items"][0]["id"]
    assert scheduler(client).storage.queue_pop(queue_key("generation")) == batch_item_token(first_item_id)
    assert scheduler(client)._claim_batch_item(first_item_id)
    response = client.post(f"/api/v1/batch-jobs/{batch_id}/cancel")

    assert response.status_code == 409
    assert response.json()["detail"] == "批量任务正在生成中，无法取消"
    detail = client.get(f"/api/v1/batch-jobs/{batch_id}").json()
    assert detail["status"] == "running"
    assert detail["items"][0]["status"] == "running"
    assert detail["items"][1]["status"] == "queued"
    assert scheduler(client).queue_items("generation") == [
        batch_item_token(detail["items"][1]["id"])
    ]


def test_batch_terminal_notification_is_idempotent(client) -> None:
    asset_id = upload_asset(client)
    created = client.post("/api/v1/batch-jobs", json=batch_payload(asset_id))
    assert created.status_code == 201, created.text
    batch_id = created.json()["id"]

    drain_generation(client)
    assert scheduler(client).reconcile_notifications() == 0

    with client.app.state.session_factory() as session:
        batch = session.get(BatchJob, batch_id)
        notifications = session.scalars(
            select(Notification).where(
                Notification.user_id == batch.user_id,
                Notification.category == "batch",
            )
        ).all()
        assert len(notifications) == 1
        metadata = json.loads(notifications[0].metadata_json)
        assert metadata == {
            "batch_job_id": batch_id,
            "business_type": "suite",
            "status": "succeeded",
            "completed_count": 2,
            "failed_count": 0,
            "total_count": 2,
        }


def test_rebuild_restores_generation_and_batch_tokens_in_fifo_order(client) -> None:
    asset_id = upload_asset(client)
    ordinary = client.post(
        "/api/v1/generation-jobs",
        json={
            "asset_ids": [asset_id],
            "platform": "Amazon",
            "market": "美国",
            "language": "English",
            "aspect_ratio": "1:1",
            "selling_points": "队列商品",
            "mode": "smart",
            "count": 7,
            "dry_run": True,
        },
    )
    assert ordinary.status_code == 201, ordinary.text
    generation_id = ordinary.json()["id"]
    batch = client.post("/api/v1/batch-jobs", json=batch_payload(asset_id))
    assert batch.status_code == 201, batch.text
    batch_id = batch.json()["id"]

    scheduler(client).storage.queue_clear(queue_key("generation"))
    counts = scheduler(client).rebuild()

    assert counts == {"generation": 3, "video": 0}
    with client.app.state.session_factory() as session:
        item_ids = session.scalars(
            select(BatchItem.id).where(BatchItem.batch_job_id == batch_id).order_by(BatchItem.index)
        ).all()
    assert scheduler(client).queue_items("generation") == [
        generation_id,
        batch_item_token(item_ids[0]),
        batch_item_token(item_ids[1]),
    ]
    drain_generation(client)
    assert client.get(f"/api/v1/generation-jobs/{generation_id}").json()["status"] == "succeeded"
    assert client.get(f"/api/v1/batch-jobs/{batch_id}").json()["status"] == "succeeded"


def test_retry_enqueues_only_failed_batch_items(client) -> None:
    asset_id = upload_asset(client)
    created = client.post("/api/v1/batch-jobs", json=batch_payload(asset_id))
    assert created.status_code == 201, created.text
    batch_id = created.json()["id"]
    drain_generation(client)

    with client.app.state.session_factory() as session:
        batch = session.get(BatchJob, batch_id)
        failed_item = batch.items[0]
        failed_child = session.get(GenerationJob, failed_item.generation_job_id)
        batch.status = "partial_failed"
        failed_item.status = "failed"
        failed_item.error = "simulated provider failure"
        failed_child.status = "failed"
        failed_child.error = "simulated provider failure"
        session.commit()

    response = client.post(f"/api/v1/batch-jobs/{batch_id}/retry-failed")

    assert response.status_code == 200, response.text
    batch = response.json()
    assert batch["status"] == "queued"
    assert batch["items"][0]["status"] == "queued"
    assert batch["items"][1]["status"] == "succeeded"
    assert scheduler(client).queue_items("generation") == [
        batch_item_token(batch["items"][0]["id"])
    ]


def test_partial_redis_enqueue_failure_fails_closed_and_releases_quota(client, monkeypatch) -> None:
    asset_id = upload_asset(client)
    sched = scheduler(client)
    generation_key = queue_key("generation")
    original_push = sched.storage.queue_push
    pushes = 0

    def fail_second_batch_push(key: str, value: str) -> None:
        nonlocal pushes
        if key == generation_key and value.startswith("batch_item:"):
            pushes += 1
            if pushes == 2:
                raise StorageUnavailableError("redis failed on second batch token")
        original_push(key, value)

    monkeypatch.setattr(sched.storage, "queue_push", fail_second_batch_push)
    response = client.post("/api/v1/batch-jobs", json=batch_payload(asset_id))

    assert response.status_code == 503
    assert response.json()["detail"] == "后台队列暂不可用，请稍后重试"
    assert sched.queue_length("generation") == 0
    with client.app.state.session_factory() as session:
        batch_rows = session.scalars(select(BatchJob)).all()
        assert len(batch_rows) == 1
        batch = batch_rows[0]
        assert batch.status == "cancelled"
        assert all(item.status == "cancelled" for item in batch.items)
        assert all(
            session.get(GenerationJob, item.generation_job_id).status == "cancelled"
            for item in batch.items
        )
