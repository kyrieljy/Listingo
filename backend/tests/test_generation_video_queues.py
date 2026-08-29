from __future__ import annotations

import asyncio
import json
import uuid

from sqlalchemy import select

from backend.app.core.storage.base import StorageUnavailableError
from backend.app.core.storage.keys import queue_key
from backend.app.models import (
    GenerationItem,
    GenerationJob,
    Notification,
    Prompt,
    VideoItem,
    VideoJob,
    Workflow,
    User,
    utcnow,
)
from backend.app.services.generation_queues import GenerationQueueScheduler
from backend.app.services.jobs import cancel_generation_job
from backend.app.services.notifications import create_job_result_notification_once
from backend.app.services.video_jobs import cancel_video_job
from backend.app.services.workspace_recovery import recover_interrupted_workspace_jobs


def _scheduler(client) -> GenerationQueueScheduler:
    return client.app.state.generation_queue_scheduler


def _session_factory(client):
    return client.app.state.session_factory


def _prompt_version_id(client, code: str) -> str:
    with _session_factory(client)() as session:
        prompt = session.scalar(select(Prompt).where(Prompt.code == code))
        assert prompt is not None and prompt.active_version_id
        return prompt.active_version_id


def _workflow_version_id(client, code: str) -> str:
    with _session_factory(client)() as session:
        workflow = session.scalar(select(Workflow).where(Workflow.code == code))
        assert workflow is not None and workflow.active_version_id
        return workflow.active_version_id


def _make_user_id(client) -> str:
    suffix = uuid.uuid4().hex[:12]
    user_id = f"qu-{suffix}"
    with _session_factory(client)() as session:
        session.add(
            User(
                id=user_id,
                phone=f"139{suffix}",
                username=user_id,
                display_name="Queue User",
                uid=user_id,
            )
        )
        session.commit()
    return user_id


def _make_png() -> bytes:
    from io import BytesIO

    from PIL import Image

    buffer = BytesIO()
    # Uploads are validated at a minimum of 128x128.
    Image.new("RGB", (128, 128), (255, 255, 255)).save(buffer, format="PNG")
    return buffer.getvalue()


def _upload_asset(client) -> str:
    response = client.post(
        "/api/v1/assets",
        files={"file": ("product.png", _make_png(), "image/png")},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _drive(client, kind: str) -> None:
    """Run exactly one queued job to completion, mirroring the worker loop."""
    asyncio.run(_scheduler(client).tick(kind))


def _create_generation_job(client, asset_id: str):
    return client.post(
        "/api/v1/generation-jobs",
        json={
            "asset_ids": [asset_id],
            "platform": "Amazon",
            "market": "美国",
            "language": "English",
            "aspect_ratio": "1:1",
            "selling_points": "保温杯",
            "mode": "smart",
            "count": 7,
            "dry_run": True,
        },
    )


def _create_video_job(client, asset_id: str):
    return client.post(
        "/api/v1/video-jobs",
        json={
            "asset_ids": [asset_id],
            "platform": "TikTok",
            "market": "北美",
            "country": "美国",
            "language": "英语",
            "aspect_ratio": "9:16",
            "selling_points": "便携、防漏、适合通勤",
            "video_types": ["UGC 种草"],
            "dry_run": True,
        },
    )


def test_scheduler_queue_is_fifo_and_removable(client) -> None:
    sched = _scheduler(client)
    sched.enqueue("generation", "a")
    sched.enqueue("generation", "b")
    sched.enqueue("video", "v")

    assert sched.queue_length("generation") == 2
    assert sched.queue_items("generation") == ["a", "b"]
    assert sched.queue_length("video") == 1

    # FIFO pop consumes the oldest element first.
    popped = sched.storage.queue_pop(queue_key("generation"))
    assert popped == "a"
    assert sched.queue_length("generation") == 1

    assert sched.remove("generation", "b") is True
    assert sched.queue_length("generation") == 0


def test_scheduler_rebuild_restores_only_queued_jobs_in_fifo(client) -> None:
    sched = _scheduler(client)
    uid = _make_user_id(client)
    pv = _prompt_version_id(client, "ecommerce-meta")
    wv = _workflow_version_id(client, "product-suite-v1")
    vpv = _prompt_version_id(client, "ecommerce-video-meta-15s")

    # Seed DB with a mix of statuses across both surfaces.
    with _session_factory(client)() as session:
        session.add(GenerationJob(id="db-queued-g", user_id=uid, status="queued", dry_run=True, params_json="{}", asset_ids_json="[]", count=1, prompt_version_id=pv, workflow_version_id=wv))
        session.add(GenerationJob(id="db-running-g", user_id=uid, status="running", dry_run=True, params_json="{}", asset_ids_json="[]", count=1, prompt_version_id=pv, workflow_version_id=wv))
        session.add(GenerationJob(id="db-cancelled-g", user_id=uid, status="cancelled", dry_run=True, params_json="{}", asset_ids_json="[]", count=1, prompt_version_id=pv, workflow_version_id=wv))
        session.add(VideoJob(id="db-queued-v", user_id=uid, status="queued", dry_run=True, params_json="{}", asset_ids_json="[]", count=1, prompt_version_id=vpv))
        session.add(VideoJob(id="db-failed-v", user_id=uid, status="failed", dry_run=True, params_json="{}", asset_ids_json="[]", count=1, prompt_version_id=vpv))
        session.commit()

    counts = sched.rebuild()

    # Only queued jobs are restored; running/cancelled/failed are left for other paths.
    assert counts["generation"] == 1
    assert counts["video"] == 1
    assert sched.queue_items("generation") == ["db-queued-g"]
    assert sched.queue_items("video") == ["db-queued-v"]


def test_tick_runs_queued_generation_job_and_writes_notification(client, monkeypatch) -> None:
    sched = _scheduler(client)
    uid = _make_user_id(client)
    pv = _prompt_version_id(client, "ecommerce-meta")
    wv = _workflow_version_id(client, "product-suite-v1")

    with _session_factory(client)() as session:
        job = GenerationJob(id="tick-g1", user_id=uid, status="queued", dry_run=True, params_json="{}", asset_ids_json="[]", count=1, prompt_version_id=pv, workflow_version_id=wv)
        session.add(job)
        session.add(GenerationItem(job_id="tick-g1", index=0, image_type="hero", prompt_text="{}", status="queued"))
        session.commit()

    sched.enqueue("generation", "tick-g1")

    async def fake_run(job_id: str, session_factory, settings, cipher) -> None:
        with session_factory() as s:
            j = s.get(GenerationJob, job_id)
            j.status = "succeeded"
            j.completed_at = utcnow()
            for item in j.items:
                item.status = "succeeded"
            s.commit()

    monkeypatch.setattr("backend.app.services.generation_queues.run_generation_job", fake_run)

    consumed = asyncio.run(sched.tick("generation"))
    assert consumed is True

    with _session_factory(client)() as session:
        finished = session.get(GenerationJob, "tick-g1")
        assert finished.status == "succeeded"
        notifications = session.scalars(
            select(Notification).where(
                Notification.user_id == uid,
                Notification.category == "generation",
            )
        ).all()
        assert notifications
        metas = [json.loads(n.metadata_json or "{}") for n in notifications]
        assert any(m.get("job_id") == "tick-g1" and m.get("status") == "succeeded" for m in metas)


def test_tick_does_not_execute_non_queued_job(client, monkeypatch) -> None:
    sched = _scheduler(client)
    uid = _make_user_id(client)
    pv = _prompt_version_id(client, "ecommerce-meta")
    wv = _workflow_version_id(client, "product-suite-v1")

    with _session_factory(client)() as session:
        job = GenerationJob(id="running-g1", user_id=uid, status="running", dry_run=True, params_json="{}", asset_ids_json="[]", count=1, prompt_version_id=pv, workflow_version_id=wv)
        session.add(job)
        session.add(GenerationItem(job_id="running-g1", index=0, image_type="hero", prompt_text="{}", status="running"))
        session.commit()

    sched.enqueue("generation", "running-g1")

    executed = {"hit": False}

    async def fake_run(job_id: str, session_factory, settings, cipher) -> None:
        executed["hit"] = True

    monkeypatch.setattr("backend.app.services.generation_queues.run_generation_job", fake_run)

    consumed = asyncio.run(sched.tick("generation"))
    assert consumed is True  # stale element is consumed from the queue
    assert executed["hit"] is False  # but the run function must not execute

    with _session_factory(client)() as session:
        assert session.get(GenerationJob, "running-g1").status == "running"


def test_cancel_generation_job_only_queued(client) -> None:
    uid = _make_user_id(client)
    pv = _prompt_version_id(client, "ecommerce-meta")
    wv = _workflow_version_id(client, "product-suite-v1")

    # queued -> cancellable
    with _session_factory(client)() as session:
        job = GenerationJob(id="cq-g", user_id=uid, status="queued", dry_run=True, params_json="{}", asset_ids_json="[]", count=1, prompt_version_id=pv, workflow_version_id=wv)
        session.add(job)
        session.add(GenerationItem(job_id="cq-g", index=0, image_type="hero", prompt_text="{}", status="queued"))
        session.commit()

    with _session_factory(client)() as session:
        job = session.get(GenerationJob, "cq-g")
        cancel_generation_job(session, job)
        session.commit()
        assert job.status == "cancelled"
        assert job.items[0].status == "cancelled"

    # running -> untouched (endpoint returns 409 before reaching here)
    with _session_factory(client)() as session:
        job = GenerationJob(id="cr-g", user_id=uid, status="running", dry_run=True, params_json="{}", asset_ids_json="[]", count=1, prompt_version_id=pv, workflow_version_id=wv)
        session.add(job)
        session.add(GenerationItem(job_id="cr-g", index=0, image_type="hero", prompt_text="{}", status="running"))
        session.commit()

    with _session_factory(client)() as session:
        job = session.get(GenerationJob, "cr-g")
        cancel_generation_job(session, job)
        session.commit()
        assert job.status == "running"


def test_cancel_video_job_only_queued(client) -> None:
    uid = _make_user_id(client)
    vpv = _prompt_version_id(client, "ecommerce-video-meta-15s")

    with _session_factory(client)() as session:
        job = VideoJob(id="cq-v", user_id=uid, status="queued", dry_run=True, params_json="{}", asset_ids_json="[]", count=1, prompt_version_id=vpv)
        session.add(job)
        session.add(VideoItem(job_id="cq-v", index=0, video_type="ugc", status="queued"))
        session.commit()

    with _session_factory(client)() as session:
        job = session.get(VideoJob, "cq-v")
        cancel_video_job(session, job)
        session.commit()
        assert job.status == "cancelled"
        assert job.items[0].status == "cancelled"

    with _session_factory(client)() as session:
        job = VideoJob(id="cr-v", user_id=uid, status="running", dry_run=True, params_json="{}", asset_ids_json="[]", count=1, prompt_version_id=vpv)
        session.add(job)
        session.add(VideoItem(job_id="cr-v", index=0, video_type="ugc", status="running"))
        session.commit()

    with _session_factory(client)() as session:
        job = session.get(VideoJob, "cr-v")
        cancel_video_job(session, job)
        session.commit()
        assert job.status == "running"


def test_recovery_preserves_queued_jobs_for_queue(client) -> None:
    uid = _make_user_id(client)
    pv = _prompt_version_id(client, "ecommerce-meta")
    wv = _workflow_version_id(client, "product-suite-v1")
    vpv = _prompt_version_id(client, "ecommerce-video-meta-15s")

    with _session_factory(client)() as session:
        # queued jobs must survive restart and be rebuilt by the queue
        gq = GenerationJob(id="rq-g", user_id=uid, status="queued", dry_run=True, params_json="{}", asset_ids_json="[]", count=1, prompt_version_id=pv, workflow_version_id=wv)
        session.add(gq)
        session.add(GenerationItem(job_id="rq-g", index=0, image_type="hero", prompt_text="{}", status="queued"))
        vq = VideoJob(id="rq-v", user_id=uid, status="queued", dry_run=True, params_json="{}", asset_ids_json="[]", count=1, prompt_version_id=vpv)
        session.add(vq)
        session.add(VideoItem(job_id="rq-v", index=0, video_type="ugc", status="queued"))
        # a running job is interrupted and must be settled
        gr = GenerationJob(id="rr-g", user_id=uid, status="running", dry_run=True, params_json="{}", asset_ids_json="[]", count=1, prompt_version_id=pv, workflow_version_id=wv)
        session.add(gr)
        session.commit()

    with _session_factory(client)() as session:
        assert recover_interrupted_workspace_jobs(session) == 1

    with _session_factory(client)() as session:
        assert session.get(GenerationJob, "rq-g").status == "queued"
        assert session.get(VideoJob, "rq-v").status == "queued"
        assert session.get(GenerationJob, "rr-g").status == "failed"


# --- API level: prove the endpoints buffer instead of executing inline ---------


def test_api_create_generation_job_enqueues_without_executing(client) -> None:
    sched = _scheduler(client)
    asset_id = _upload_asset(client)

    response = _create_generation_job(client, asset_id)
    assert response.status_code == 201, response.text
    job_id = response.json()["id"]

    # Buffered, not executed: the call returns a queued job sitting in the buffer.
    assert response.json()["status"] == "queued"
    assert job_id in sched.queue_items("generation")
    assert client.get(f"/api/v1/generation-jobs/{job_id}").json()["status"] == "queued"

    # Only a worker tick advances it to a terminal state and drains the buffer.
    _drive(client, "generation")
    assert client.get(f"/api/v1/generation-jobs/{job_id}").json()["status"] == "succeeded"
    assert job_id not in sched.queue_items("generation")


def test_api_create_video_job_enqueues_without_executing(client) -> None:
    sched = _scheduler(client)
    asset_id = _upload_asset(client)

    response = _create_video_job(client, asset_id)
    assert response.status_code == 201, response.text
    job_id = response.json()["id"]

    assert response.json()["status"] == "queued"
    assert job_id in sched.queue_items("video")
    assert client.get(f"/api/v1/video-jobs/{job_id}").json()["status"] == "queued"

    _drive(client, "video")
    assert client.get(f"/api/v1/video-jobs/{job_id}").json()["status"] == "succeeded"
    assert job_id not in sched.queue_items("video")


def test_api_retry_failed_enqueues_without_executing(client, monkeypatch) -> None:
    sched = _scheduler(client)
    asset_id = _upload_asset(client)

    created = _create_generation_job(client, asset_id)
    assert created.status_code == 201, created.text
    job_id = created.json()["id"]
    _drive(client, "generation")

    # retry-failed only accepts live (non dry_run) jobs; the retry runner is stubbed
    # so draining the queue never reaches an external provider.
    with _session_factory(client)() as session:
        job = session.get(GenerationJob, job_id)
        job.dry_run = False
        job.status = "failed"
        job.items[0].status = "failed"
        job.items[0].error = "provider exception"
        session.commit()

    async def fake_retry(job_id: str, session_factory, settings, cipher) -> None:
        with session_factory() as s:
            j = s.get(GenerationJob, job_id)
            j.status = "succeeded"
            j.completed_at = utcnow()
            for item in j.items:
                item.status = "succeeded"
            s.commit()

    monkeypatch.setattr(
        "backend.app.services.generation_queues.retry_failed_live_items", fake_retry
    )

    retry = client.post(f"/api/v1/generation-jobs/{job_id}/retry-failed")
    assert retry.status_code == 200, retry.text

    # Buffered, not executed inline: the job is queued and sits in the buffer.
    assert retry.json()["status"] == "queued"
    assert job_id in sched.queue_items("generation")

    _drive(client, "generation")
    with _session_factory(client)() as session:
        assert session.get(GenerationJob, job_id).status == "succeeded"


def test_api_cancel_queued_generation_job_cancels_and_drains_queue(client) -> None:
    sched = _scheduler(client)
    asset_id = _upload_asset(client)

    created = _create_generation_job(client, asset_id)
    assert created.status_code == 201, created.text
    job_id = created.json()["id"]
    assert job_id in sched.queue_items("generation")

    response = client.post(f"/api/v1/generation-jobs/{job_id}/cancel")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "cancelled"
    assert job_id not in sched.queue_items("generation")


def test_api_cancel_running_generation_job_returns_409(client) -> None:
    asset_id = _upload_asset(client)
    created = _create_generation_job(client, asset_id)
    assert created.status_code == 201, created.text
    job_id = created.json()["id"]

    # Simulate the worker having already claimed the job.
    with _session_factory(client)() as session:
        job = session.get(GenerationJob, job_id)
        job.status = "running"
        for item in job.items:
            item.status = "running"
        session.commit()

    response = client.post(f"/api/v1/generation-jobs/{job_id}/cancel")
    assert response.status_code == 409
    assert "无法取消" in response.json()["detail"]

    # The job must stay running; it is never flipped to `cancelling`.
    with _session_factory(client)() as session:
        assert session.get(GenerationJob, job_id).status == "running"


def test_terminal_notification_is_written_once_per_job(client) -> None:
    uid = _make_user_id(client)

    with _session_factory(client)() as session:
        create_job_result_notification_once(
            session, uid, category="generation", job_id="notif-g1", status="partial_failed", dry_run=True
        )
        session.commit()

    # Replaying (duplicate consumption / compensation scan) must not duplicate it.
    with _session_factory(client)() as session:
        create_job_result_notification_once(
            session, uid, category="generation", job_id="notif-g1", status="partial_failed", dry_run=True
        )
        session.commit()
        rows = session.scalars(select(Notification).where(Notification.user_id == uid)).all()
        assert len(rows) == 1
        assert "部分完成" in rows[0].title


def test_api_create_returns_503_and_leaves_no_queued_job_when_redis_is_down(client, monkeypatch) -> None:
    sched = _scheduler(client)
    asset_id = _upload_asset(client)

    def boom(kind: str, job_id: str) -> None:
        raise StorageUnavailableError("redis is down")

    monkeypatch.setattr(sched, "enqueue", boom)

    response = _create_generation_job(client, asset_id)
    assert response.status_code == 503

    # fail-closed: nothing is left behind that a worker could pick up later.
    assert sched.queue_length("generation") == 0
    with _session_factory(client)() as session:
        queued = session.scalars(select(GenerationJob).where(GenerationJob.status == "queued")).all()
        assert not queued
