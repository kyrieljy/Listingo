from io import BytesIO
from datetime import datetime, timedelta, timezone
import json
from zipfile import ZipFile

import pytest
from PIL import Image
from sqlalchemy import select

from backend.app.api import admin as admin_api
from backend.app.api.public import build_copywriting_user_prompt
from backend.app.models import (
    AplusItem,
    AplusJob,
    BatchItem,
    BatchJob,
    GenerationItem,
    GenerationJob,
    Provider,
    Prompt,
    VideoItem,
    VideoJob,
    Workflow,
)
from backend.app.schemas import A_PLUS_MODULES, CopywritingAssistCreate, VIDEO_TYPES
from backend.app.services.aplus_jobs import DEMO_ASSETS
from backend.app.services.jobs import INVALID_GENERATED_IMAGE_ERROR, validate_generated_image_bytes
from backend.app.services.workspace_recovery import recover_interrupted_workspace_jobs, repair_monitoring_fixture_history


def make_png() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (640, 640), "#f2ede4").save(buffer, format="PNG")
    return buffer.getvalue()


def upload_asset(client) -> str:
    response = client.post(
        "/api/v1/assets",
        files={"file": ("product.png", make_png(), "image/png")},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def active_prompt_version_id(client, code: str) -> str:
    with client.app.state.session_factory() as session:
        prompt = session.scalar(select(Prompt).where(Prompt.code == code))
        assert prompt is not None and prompt.active_version_id
        return prompt.active_version_id


def active_workflow_version_id(client, code: str) -> str:
    with client.app.state.session_factory() as session:
        workflow = session.scalar(select(Workflow).where(Workflow.code == code))
        assert workflow is not None and workflow.active_version_id
        return workflow.active_version_id


def test_admin_ocr_settings_can_be_updated_and_prewarmed(client, monkeypatch) -> None:
    current = client.get("/api/v1/admin/ocr-settings")
    assert current.status_code == 200
    assert current.json()["ocr_engine"] == "rapidocr"
    assert current.json()["ocr_primary_model"] == "PP-OCRv5"

    updated = client.patch(
        "/api/v1/admin/ocr-settings",
        json={
            "ocr_engine": "rapidocr",
            "ocr_primary_model": "PP-OCRv5",
            "ocr_fallback_model": "PP-OCRv6",
            "ocr_text_score_threshold": 0.7,
            "ocr_min_box_width": 8,
            "ocr_use_enhanced_variants": True,
        },
    )
    assert updated.status_code == 200, updated.text
    data = updated.json()
    assert data["ocr_engine"] == "rapidocr"
    assert data["ocr_primary_model"] == "PP-OCRv5"
    assert data["ocr_text_score_threshold"] == 0.7
    assert data["ocr_min_box_width"] == 8
    assert data["ocr_use_enhanced_variants"] is True

    def fake_prewarm(settings):
        assert settings.ocr_engine == "rapidocr"
        return {
            "ok": True,
            "active_engine": "RapidOCR",
            "active_model": "PP-OCRv4-onnx",
            "elapsed_ms": 12,
            "warmed": [{"engine": "RapidOCR", "model": "PP-OCRv4-onnx", "ok": True, "elapsed_ms": 12}],
            "warning": None,
            "cache_size": 1,
        }

    monkeypatch.setattr(admin_api, "prewarm_ocr_engine", fake_prewarm)
    prewarm = client.post("/api/v1/admin/ocr-settings/prewarm")
    assert prewarm.status_code == 200, prewarm.text
    assert prewarm.json()["prewarm"]["active_engine"] == "RapidOCR"


def test_admin_ocr_settings_reject_invalid_engine(client) -> None:
    response = client.patch("/api/v1/admin/ocr-settings", json={"ocr_engine": "unknown"})
    assert response.status_code == 422


def test_generated_image_validation_reports_readable_error() -> None:
    with pytest.raises(RuntimeError) as exc_info:
        validate_generated_image_bytes(b'{"error":"not an image"}')
    assert INVALID_GENERATED_IMAGE_ERROR in str(exc_info.value)
    assert "BytesIO" not in str(exc_info.value)


def test_dryrun_job_completes_without_external_calls_and_exports_zip(client) -> None:
    asset_id = upload_asset(client)
    response = client.post(
        "/api/v1/generation-jobs",
        json={
            "asset_ids": [asset_id],
            "platform": "Amazon",
            "market": "美国",
            "language": "English",
            "aspect_ratio": "1:1",
            "selling_points": "双层保温，防滑握持，通勤便携",
            "mode": "smart",
            "count": 7,
            "dry_run": True,
        },
    )
    assert response.status_code == 201, response.text
    job = response.json()
    detail = client.get(f"/api/v1/generation-jobs/{job['id']}").json()

    assert detail["status"] == "succeeded"
    assert detail["progress"] == 100
    assert len(detail["items"]) == 7
    assert all(item["status"] == "succeeded" for item in detail["items"])
    assert all(item["prompt_text"] for item in detail["items"])
    assert json.loads(detail["items"][0]["prompt_text"])["image_type"]
    assert all(item["versions"][0]["url"].startswith("/files/results/") for item in detail["items"])

    item_ids = ",".join(item["id"] for item in detail["items"][:3])
    source_path = client.app.state.settings.data_dir / detail["items"][0]["versions"][0]["url"].removeprefix("/files/")
    original_source_bytes = source_path.read_bytes()
    archive = client.get(
        f"/api/v1/generation-jobs/{job['id']}/download",
        params={"item_ids": item_ids},
    )
    assert archive.status_code == 200
    assert archive.headers["content-type"] == "application/zip"
    with ZipFile(BytesIO(archive.content)) as zip_file:
        assert len(zip_file.namelist()) == 3
        watermarked_name = zip_file.namelist()[0]
        watermarked_bytes = zip_file.read(watermarked_name)

    plain_archive = client.get(
        f"/api/v1/generation-jobs/{job['id']}/download",
        params={"item_ids": item_ids, "include_watermark": False},
    )
    assert plain_archive.status_code == 200
    with ZipFile(BytesIO(plain_archive.content)) as zip_file:
        plain_bytes = zip_file.read(zip_file.namelist()[0])
    with Image.open(BytesIO(watermarked_bytes)) as watermarked, Image.open(BytesIO(plain_bytes)) as plain:
        assert watermarked.size == plain.size
    assert watermarked_bytes != plain_bytes
    assert source_path.read_bytes() == original_source_bytes

    long_image = client.get(
        f"/api/v1/generation-jobs/{job['id']}/download",
        params={"item_ids": item_ids, "format": "long_image"},
    )
    assert long_image.status_code == 200
    assert long_image.headers["content-type"] == "image/png"
    with Image.open(BytesIO(long_image.content)) as image:
        assert image.height > image.width


def test_generation_cancel_marks_unstarted_items_and_is_idempotent(client) -> None:
    prompt_version_id = active_prompt_version_id(client, "ecommerce-meta")
    workflow_version_id = active_workflow_version_id(client, "product-suite-v1")
    with client.app.state.session_factory() as session:
        job = GenerationJob(
            status="running",
            dry_run=True,
            params_json="{}",
            asset_ids_json="[]",
            count=3,
            progress=30,
            prompt_version_id=prompt_version_id,
            workflow_version_id=workflow_version_id,
        )
        session.add(job)
        session.flush()
        session.add_all(
            [
                GenerationItem(job_id=job.id, index=0, image_type="hero", prompt_text="{}", status="succeeded"),
                GenerationItem(job_id=job.id, index=1, image_type="queued", prompt_text="{}", status="queued"),
                GenerationItem(job_id=job.id, index=2, image_type="running", prompt_text="{}", status="running"),
            ]
        )
        session.commit()
        job_id = job.id

    response = client.post(f"/api/v1/generation-jobs/{job_id}/cancel")
    assert response.status_code == 200, response.text
    cancelled = response.json()
    assert cancelled["status"] == "cancelling"
    assert [item["status"] for item in cancelled["items"]] == ["succeeded", "cancelled", "running"]

    repeated = client.post(f"/api/v1/generation-jobs/{job_id}/cancel")
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["status"] == "cancelling"


def test_aplus_cancel_endpoints_are_idempotent_and_preserve_successes(client) -> None:
    prompt_version_id = active_prompt_version_id(client, "aplus-meta")
    with client.app.state.session_factory() as session:
        plan_job = AplusJob(
            job_type="plan",
            status="queued",
            dry_run=True,
            params_json="{}",
            asset_ids_json="[]",
            count=1,
            prompt_version_id=prompt_version_id,
        )
        generation_job = AplusJob(
            job_type="generation",
            status="running",
            dry_run=True,
            params_json="{}",
            asset_ids_json="[]",
            count=2,
            prompt_version_id=prompt_version_id,
        )
        session.add_all([plan_job, generation_job])
        session.flush()
        session.add(AplusItem(job_id=plan_job.id, index=0, module_index=1, module_name="hero", prompt_text="{}", status="queued"))
        session.add_all(
            [
                AplusItem(job_id=generation_job.id, index=0, module_index=1, module_name="hero", prompt_text="{}", status="succeeded"),
                AplusItem(job_id=generation_job.id, index=1, module_index=2, module_name="detail", prompt_text="{}", status="queued"),
            ]
        )
        session.commit()
        plan_job_id = plan_job.id
        generation_job_id = generation_job.id

    plan_cancel = client.post(f"/api/v1/aplus-plan-jobs/{plan_job_id}/cancel")
    assert plan_cancel.status_code == 200, plan_cancel.text
    assert plan_cancel.json()["status"] == "cancelled"
    assert client.post(f"/api/v1/aplus-plan-jobs/{plan_job_id}/cancel").json()["status"] == "cancelled"

    generation_cancel = client.post(f"/api/v1/aplus-generation-jobs/{generation_job_id}/cancel")
    assert generation_cancel.status_code == 200, generation_cancel.text
    generation_payload = generation_cancel.json()
    assert generation_payload["status"] == "partial_cancelled"
    assert [item["status"] for item in generation_payload["items"]] == ["succeeded", "cancelled"]


def test_aplus_single_item_retry_only_reruns_target_failed_item(client) -> None:
    asset_id = upload_asset(client)
    prompt_version_id = active_prompt_version_id(client, "aplus-meta")
    with client.app.state.session_factory() as session:
        job = AplusJob(
            job_type="generation",
            status="partial_failed",
            dry_run=True,
            params_json=json.dumps({"output_targets": [{"mode": "detail", "aspect_ratio": "1:1"}]}, ensure_ascii=False),
            asset_ids_json=json.dumps([asset_id]),
            count=2,
            prompt_version_id=prompt_version_id,
        )
        session.add(job)
        session.flush()
        target = AplusItem(
            job_id=job.id,
            index=0,
            module_index=1,
            module_name="商品主视觉",
            output_mode="detail",
            aspect_ratio="1:1",
            image_prompt="主视觉",
            copy_requirements="No Text Overlay",
            prompt_text="{}",
            status="failed",
            error="target failed",
        )
        other = AplusItem(
            job_id=job.id,
            index=1,
            module_index=2,
            module_name="卖点拆解",
            output_mode="detail",
            aspect_ratio="1:1",
            image_prompt="卖点",
            copy_requirements="No Text Overlay",
            prompt_text="{}",
            status="failed",
            error="other failed",
        )
        session.add_all([target, other])
        session.commit()
        target_id = target.id
        other_id = other.id

    response = client.post(f"/api/v1/aplus-items/{target_id}/retry")

    assert response.status_code == 200, response.text
    payload = response.json()
    by_id = {item["id"]: item for item in payload["items"]}
    assert by_id[target_id]["status"] == "succeeded"
    assert by_id[target_id]["versions"]
    assert by_id[other_id]["status"] == "failed"
    assert by_id[other_id]["error"] == "other failed"
    assert payload["status"] == "partial_failed"


def test_suite_single_item_retry_only_reruns_target_failed_item(client) -> None:
    asset_id = upload_asset(client)
    prompt_version_id = active_prompt_version_id(client, "ecommerce-meta")
    workflow_version_id = active_workflow_version_id(client, "product-suite-v1")
    with client.app.state.session_factory() as session:
        job = GenerationJob(
            status="partial_failed",
            dry_run=True,
            params_json=json.dumps({"aspect_ratio": "1:1", "model_preference": "fidelity"}, ensure_ascii=False),
            asset_ids_json=json.dumps([asset_id]),
            count=2,
            prompt_version_id=prompt_version_id,
            workflow_version_id=workflow_version_id,
        )
        session.add(job)
        session.flush()
        target = GenerationItem(
            job_id=job.id,
            index=0,
            route_symbol="#@",
            image_type="主图",
            prompt_text="{}",
            status="failed",
            error="target failed",
        )
        other = GenerationItem(
            job_id=job.id,
            index=1,
            route_symbol="#@",
            image_type="卖点图",
            prompt_text="{}",
            status="failed",
            error="other failed",
        )
        session.add_all([target, other])
        session.commit()
        target_id = target.id
        other_id = other.id

    response = client.post(f"/api/v1/generation-items/{target_id}/retry")

    assert response.status_code == 200, response.text
    payload = response.json()
    by_id = {item["id"]: item for item in payload["items"]}
    assert by_id[target_id]["status"] == "succeeded"
    assert by_id[target_id]["versions"]
    assert by_id[other_id]["status"] == "failed"
    assert by_id[other_id]["error"] == "other failed"
    assert payload["status"] == "partial_failed"


def test_aplus_plan_history_lists_active_user_plans_newest_first(client) -> None:
    prompt_version_id = active_prompt_version_id(client, "aplus-meta")
    now = datetime.now(timezone.utc)
    with client.app.state.session_factory() as session:
        older = AplusJob(
            job_type="plan",
            status="running",
            dry_run=True,
            params_json='{"module_selections":[{"name":"商品主视觉","count":1}],"output_targets":[{"mode":"detail","aspect_ratio":"1:1"}]}',
            asset_ids_json="[]",
            count=1,
            prompt_version_id=prompt_version_id,
            created_at=now - timedelta(minutes=2),
        )
        newest = AplusJob(
            job_type="plan",
            status="queued",
            dry_run=True,
            params_json='{"module_selections":[{"name":"卖点拆解","count":1}],"output_targets":[{"mode":"detail","aspect_ratio":"1:1"}]}',
            asset_ids_json="[]",
            count=1,
            prompt_version_id=prompt_version_id,
            created_at=now,
        )
        admin = AplusJob(
            job_type="plan",
            status="running",
            dry_run=True,
            is_admin_test=True,
            params_json="{}",
            asset_ids_json="[]",
            count=1,
            prompt_version_id=prompt_version_id,
            created_at=now + timedelta(minutes=1),
        )
        batch_plan = AplusJob(
            job_type="plan",
            status="running",
            dry_run=True,
            params_json="{}",
            asset_ids_json="[]",
            count=1,
            prompt_version_id=prompt_version_id,
            created_at=now + timedelta(minutes=2),
        )
        session.add_all([older, newest, admin, batch_plan])
        session.flush()
        batch = BatchJob(business_type="aplus", status="running", total_count=1)
        session.add(batch)
        session.flush()
        session.add(BatchItem(batch_job_id=batch.id, index=0, name="batch", aplus_plan_job_id=batch_plan.id))
        session.commit()
        older_id = older.id
        newest_id = newest.id
        admin_id = admin.id
        batch_plan_id = batch_plan.id

    history = client.get("/api/v1/aplus-plan-jobs")
    assert history.status_code == 200, history.text
    ids = [job["id"] for job in history.json()]
    assert ids[:2] == [newest_id, older_id]
    assert admin_id not in ids
    assert batch_plan_id not in ids


def test_history_filters_and_repairs_empty_monitoring_fixture_jobs(client) -> None:
    generation_prompt_id = active_prompt_version_id(client, "ecommerce-meta")
    workflow_version_id = active_workflow_version_id(client, "product-suite-v1")
    aplus_prompt_id = active_prompt_version_id(client, "aplus-meta")
    video_prompt_id = active_prompt_version_id(client, "ecommerce-video-meta-15s")
    with client.app.state.session_factory() as session:
        demo_generation = GenerationJob(
            id="demo-monitor-generation-empty",
            status="queued",
            dry_run=True,
            params_json="{}",
            asset_ids_json="[]",
            count=1,
            prompt_version_id=generation_prompt_id,
            workflow_version_id=workflow_version_id,
        )
        real_generation = GenerationJob(
            id="real-history-generation",
            status="succeeded",
            dry_run=True,
            params_json="{}",
            asset_ids_json="[]",
            count=1,
            progress=100,
            prompt_version_id=generation_prompt_id,
            workflow_version_id=workflow_version_id,
        )
        demo_aplus_plan = AplusJob(
            id="demo-monitor-aplus-plan-empty",
            job_type="plan",
            status="queued",
            dry_run=True,
            params_json="{}",
            asset_ids_json="[]",
            count=1,
            prompt_version_id=aplus_prompt_id,
        )
        demo_aplus_generation = AplusJob(
            id="demo-monitor-aplus-generation-empty",
            job_type="generation",
            status="queued",
            dry_run=True,
            params_json="{}",
            asset_ids_json="[]",
            count=1,
            prompt_version_id=aplus_prompt_id,
        )
        demo_video = VideoJob(
            id="demo-monitor-video-empty",
            status="queued",
            dry_run=True,
            params_json="{}",
            asset_ids_json="[]",
            count=1,
            prompt_version_id=video_prompt_id,
        )
        demo_batch = BatchJob(id="demo-monitor-batch-empty", business_type="suite", status="queued", total_count=0)
        session.add_all([demo_generation, real_generation, demo_aplus_plan, demo_aplus_generation, demo_video, demo_batch])
        session.flush()
        session.add(GenerationItem(job_id=real_generation.id, index=0, image_type="hero", prompt_text="{}", status="succeeded"))
        session.commit()

        assert repair_monitoring_fixture_history(session) == 4
        assert session.get(GenerationJob, demo_generation.id).is_admin_test is True
        assert session.get(AplusJob, demo_aplus_plan.id).is_admin_test is True
        assert session.get(AplusJob, demo_aplus_generation.id).is_admin_test is True
        assert session.get(VideoJob, demo_video.id).is_admin_test is True

    suite_ids = {job["id"] for job in client.get("/api/v1/generation-jobs").json()}
    plan_ids = {job["id"] for job in client.get("/api/v1/aplus-plan-jobs").json()}
    aplus_ids = {job["id"] for job in client.get("/api/v1/aplus-generation-jobs").json()}
    video_ids = {job["id"] for job in client.get("/api/v1/video-jobs").json()}
    batch_ids = {job["id"] for job in client.get("/api/v1/batch-jobs").json()}

    assert "real-history-generation" in suite_ids
    assert "demo-monitor-generation-empty" not in suite_ids
    assert "demo-monitor-aplus-plan-empty" not in plan_ids
    assert "demo-monitor-aplus-generation-empty" not in aplus_ids
    assert "demo-monitor-video-empty" not in video_ids
    assert "demo-monitor-batch-empty" not in batch_ids


def test_video_cancel_endpoint_cancels_queued_items_idempotently(client) -> None:
    prompt_version_id = active_prompt_version_id(client, "ecommerce-video-meta-15s")
    with client.app.state.session_factory() as session:
        job = VideoJob(
            status="queued",
            dry_run=True,
            params_json="{}",
            asset_ids_json="[]",
            count=2,
            prompt_version_id=prompt_version_id,
        )
        session.add(job)
        session.flush()
        session.add_all(
            [
                VideoItem(job_id=job.id, index=0, video_type="ugc", status="queued"),
                VideoItem(job_id=job.id, index=1, video_type="product", status="queued"),
            ]
        )
        session.commit()
        job_id = job.id

    response = client.post(f"/api/v1/video-jobs/{job_id}/cancel")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "cancelled"
    assert [item["status"] for item in payload["items"]] == ["cancelled", "cancelled"]
    assert client.post(f"/api/v1/video-jobs/{job_id}/cancel").json()["status"] == "cancelled"


def test_workspace_recovery_settles_orphaned_open_jobs_across_surfaces(client) -> None:
    generation_prompt_id = active_prompt_version_id(client, "ecommerce-meta")
    workflow_version_id = active_workflow_version_id(client, "product-suite-v1")
    aplus_prompt_id = active_prompt_version_id(client, "aplus-meta")
    video_prompt_id = active_prompt_version_id(client, "ecommerce-video-meta-15s")
    with client.app.state.session_factory() as session:
        generation_job = GenerationJob(
            status="running",
            dry_run=False,
            params_json="{}",
            asset_ids_json="[]",
            count=2,
            progress=50,
            prompt_version_id=generation_prompt_id,
            workflow_version_id=workflow_version_id,
        )
        aplus_job = AplusJob(
            job_type="generation",
            status="cancelling",
            dry_run=False,
            params_json="{}",
            asset_ids_json="[]",
            count=2,
            progress=50,
            prompt_version_id=aplus_prompt_id,
        )
        video_job = VideoJob(
            status="queued",
            dry_run=False,
            params_json="{}",
            asset_ids_json="[]",
            count=1,
            progress=0,
            prompt_version_id=video_prompt_id,
        )
        session.add_all([generation_job, aplus_job, video_job])
        session.flush()
        session.add_all(
            [
                GenerationItem(job_id=generation_job.id, index=0, image_type="hero", prompt_text="{}", status="succeeded"),
                GenerationItem(job_id=generation_job.id, index=1, image_type="scene", prompt_text="{}", status="running"),
                AplusItem(job_id=aplus_job.id, index=0, module_index=1, module_name="hero", prompt_text="{}", status="failed"),
                AplusItem(job_id=aplus_job.id, index=1, module_index=2, module_name="detail", prompt_text="{}", status="running"),
                VideoItem(job_id=video_job.id, index=0, video_type="ugc", status="queued"),
            ]
        )
        generation_job_id = generation_job.id
        aplus_job_id = aplus_job.id
        video_job_id = video_job.id
        session.commit()

    with client.app.state.session_factory() as session:
        assert recover_interrupted_workspace_jobs(session) == 3

    with client.app.state.session_factory() as session:
        generation_job = session.get(GenerationJob, generation_job_id)
        aplus_job = session.get(AplusJob, aplus_job_id)
        video_job = session.get(VideoJob, video_job_id)
        generation_statuses = session.scalars(
            select(GenerationItem.status).where(GenerationItem.job_id == generation_job_id).order_by(GenerationItem.index)
        ).all()
        aplus_statuses = session.scalars(
            select(AplusItem.status).where(AplusItem.job_id == aplus_job_id).order_by(AplusItem.index)
        ).all()
        video_statuses = session.scalars(
            select(VideoItem.status).where(VideoItem.job_id == video_job_id).order_by(VideoItem.index)
        ).all()

    assert generation_job.status == "partial_failed"
    assert generation_job.progress == 100
    assert generation_job.completed_at is not None
    assert generation_statuses == ["succeeded", "failed"]
    assert aplus_job.status == "partial_cancelled"
    assert aplus_job.progress == 100
    assert aplus_job.completed_at is not None
    assert aplus_statuses == ["failed", "cancelled"]
    assert video_job.status == "failed"
    assert video_job.progress == 100
    assert video_job.completed_at is not None
    assert video_statuses == ["failed"]


def test_workspace_recovery_leaves_batch_child_jobs_for_scheduler(client) -> None:
    generation_prompt_id = active_prompt_version_id(client, "ecommerce-meta")
    workflow_version_id = active_workflow_version_id(client, "product-suite-v1")
    aplus_prompt_id = active_prompt_version_id(client, "aplus-meta")
    with client.app.state.session_factory() as session:
        suite_child = GenerationJob(
            status="running",
            dry_run=False,
            params_json="{}",
            asset_ids_json="[]",
            count=1,
            prompt_version_id=generation_prompt_id,
            workflow_version_id=workflow_version_id,
        )
        aplus_child = AplusJob(
            job_type="generation",
            status="running",
            dry_run=False,
            params_json="{}",
            asset_ids_json="[]",
            count=1,
            prompt_version_id=aplus_prompt_id,
        )
        session.add_all([suite_child, aplus_child])
        session.flush()
        suite_item = GenerationItem(job_id=suite_child.id, index=0, image_type="hero", prompt_text="{}", status="running")
        aplus_item = AplusItem(job_id=aplus_child.id, index=0, module_index=1, module_name="hero", prompt_text="{}", status="running")
        session.add_all([suite_item, aplus_item])
        suite_batch = BatchJob(business_type="suite", status="running", total_count=1)
        aplus_batch = BatchJob(business_type="aplus", status="running", total_count=1)
        session.add_all([suite_batch, aplus_batch])
        session.flush()
        session.add_all(
            [
                BatchItem(batch_job_id=suite_batch.id, index=0, name="suite", status="running", generation_job_id=suite_child.id),
                BatchItem(batch_job_id=aplus_batch.id, index=0, name="aplus", status="running", aplus_generation_job_id=aplus_child.id),
            ]
        )
        suite_child_id = suite_child.id
        aplus_child_id = aplus_child.id
        suite_item_id = suite_item.id
        aplus_item_id = aplus_item.id
        session.commit()

    with client.app.state.session_factory() as session:
        assert recover_interrupted_workspace_jobs(session) == 0

    with client.app.state.session_factory() as session:
        assert session.get(GenerationJob, suite_child_id).status == "running"
        assert session.get(AplusJob, aplus_child_id).status == "running"
        assert session.get(GenerationItem, suite_item_id).status == "running"
        assert session.get(AplusItem, aplus_item_id).status == "running"


def test_aplus_dryrun_plan_and_generation_respect_amazon_a_plus_ratios(client) -> None:
    assert [asset.name for asset in DEMO_ASSETS] == [f"aplus-outdoor-module-{index:02d}.png" for index in range(1, 11)]
    assert len({asset.name for asset in DEMO_ASSETS}) == 10

    asset_id = upload_asset(client)
    plan_response = client.post(
        "/api/v1/aplus-plan-jobs",
        json={
            "asset_ids": [asset_id],
            "platform": "亚马逊",
            "market": "美国",
            "language": "英文",
            "product_info": "便携保温杯，适合通勤。",
            "module_selections": [
                {"name": "商品主视觉", "count": 1},
                {"name": "卖点拆解", "count": 2},
            ],
            "output_targets": [
                {"mode": "amazon_aplus_advanced_web", "aspect_ratio": "1464:600"},
                {"mode": "amazon_aplus_advanced_mobile", "aspect_ratio": "600:450"},
            ],
            "dry_run": True,
        },
    )
    assert plan_response.status_code == 201, plan_response.text
    plan = client.get(f"/api/v1/aplus-plan-jobs/{plan_response.json()['id']}").json()
    assert plan["status"] == "succeeded"
    assert plan["count"] == 3
    assert plan["params"]["module_total"] == 3
    assert plan["params"]["module_selections"] == [
        {"name": "商品主视觉", "count": 1},
        {"name": "卖点拆解", "count": 2},
    ]
    assert [item["module_name"] for item in plan["items"]] == ["商品主视觉", "卖点拆解", "卖点拆解"]

    generation_response = client.post(
        "/api/v1/aplus-generation-jobs",
        json={
            "plan_job_id": plan["id"],
            "module_item_ids": [item["id"] for item in plan["items"]],
            "output_targets": plan["params"]["output_targets"],
            "dry_run": True,
        },
    )
    assert generation_response.status_code == 201, generation_response.text
    generation = client.get(f"/api/v1/aplus-generation-jobs/{generation_response.json()['id']}").json()
    assert generation["status"] == "succeeded"
    assert len(generation["items"]) == 6
    assert {item["aspect_ratio"] for item in generation["items"]} == {"1464:600", "600:450"}
    history = client.get("/api/v1/aplus-generation-jobs").json()
    assert history[0]["id"] == generation["id"]
    assert history[0]["job_type"] == "generation"
    mobile_items = [item for item in generation["items"] if item["output_mode"] == "amazon_aplus_advanced_mobile"]
    assert len(mobile_items) == 3
    assert all(item["source_web_item_id"] for item in mobile_items)

    archive = client.get(
        f"/api/v1/aplus-generation-jobs/{generation['id']}/download",
        params={"item_ids": ",".join(item["id"] for item in generation["items"][:2])},
    )
    assert archive.status_code == 200
    assert archive.headers["content-type"] == "application/zip"
    with ZipFile(BytesIO(archive.content)) as zip_file:
        watermarked_bytes = zip_file.read(zip_file.namelist()[0])
    plain_archive = client.get(
        f"/api/v1/aplus-generation-jobs/{generation['id']}/download",
        params={"item_ids": ",".join(item["id"] for item in generation["items"][:2]), "include_watermark": False},
    )
    assert plain_archive.status_code == 200
    with ZipFile(BytesIO(plain_archive.content)) as zip_file:
        plain_bytes = zip_file.read(zip_file.namelist()[0])
    assert watermarked_bytes != plain_bytes

    aplus_long_image = client.get(
        f"/api/v1/aplus-generation-jobs/{generation['id']}/download",
        params={"item_ids": ",".join(item["id"] for item in generation["items"][:2]), "format": "long_image"},
    )
    assert aplus_long_image.status_code == 200
    assert aplus_long_image.headers["content-type"] == "image/png"
    with Image.open(BytesIO(aplus_long_image.content)) as image:
        assert image.height > 0
        assert image.width > 0

    original_item = generation["items"][0]
    original_version_id = original_item["current_version_id"]
    edited = client.post(
        f"/api/v1/aplus-items/{original_item['id']}/versions",
        json={"instruction": "Use a cleaner studio background"},
    )
    assert edited.status_code == 201, edited.text
    edited_version = edited.json()
    assert edited_version["parent_version_id"] == original_version_id
    updated = client.get(f"/api/v1/aplus-generation-jobs/{generation['id']}").json()
    updated_item = next(item for item in updated["items"] if item["id"] == original_item["id"])
    assert updated_item["current_version_id"] == edited_version["id"]
    assert len(updated_item["versions"]) == 2

    ocr = client.post(f"/api/v1/aplus-items/{original_item['id']}/text-ocr")
    assert ocr.status_code == 200, ocr.text
    assert "lines" in ocr.json()
    text_edit = client.post(
        f"/api/v1/aplus-items/{original_item['id']}/text-versions",
        json={
            "lines": [
                {
                    "id": "manual-1",
                    "index": 0,
                    "original_text": "OLD",
                    "text": "NEW",
                    "bbox": {"x": 12, "y": 24, "width": 120, "height": 32},
                }
            ]
        },
    )
    assert text_edit.status_code == 201, text_edit.text
    assert text_edit.json()["parent_version_id"] == edited_version["id"]


def test_aplus_advanced_mobile_only_uses_direct_generation_path(client) -> None:
    asset_id = upload_asset(client)
    plan_response = client.post(
        "/api/v1/aplus-plan-jobs",
        json={
            "asset_ids": [asset_id],
            "platform": "亚马逊",
            "market": "美国",
            "language": "英文",
            "product_info": "便携保温杯，适合通勤。",
            "module_selections": [
                {"name": "商品主视觉", "count": 1},
                {"name": "生活场景", "count": 1},
            ],
            "output_targets": [{"mode": "amazon_aplus_advanced_mobile", "aspect_ratio": "600:450"}],
            "dry_run": True,
        },
    )
    assert plan_response.status_code == 201, plan_response.text
    plan = client.get(f"/api/v1/aplus-plan-jobs/{plan_response.json()['id']}").json()

    generation_response = client.post(
        "/api/v1/aplus-generation-jobs",
        json={
            "plan_job_id": plan["id"],
            "module_item_ids": [item["id"] for item in plan["items"]],
            "output_targets": plan["params"]["output_targets"],
            "dry_run": True,
        },
    )
    assert generation_response.status_code == 201, generation_response.text
    generation = client.get(f"/api/v1/aplus-generation-jobs/{generation_response.json()['id']}").json()

    assert generation["status"] == "succeeded"
    assert len(generation["items"]) == 2
    assert {item["output_mode"] for item in generation["items"]} == {"amazon_aplus_advanced_mobile"}
    assert all(item["aspect_ratio"] == "600:450" for item in generation["items"])
    assert all(item["source_web_item_id"] is None for item in generation["items"])


def test_aplus_rejects_mixed_output_specs(client) -> None:
    asset_id = upload_asset(client)
    response = client.post(
        "/api/v1/aplus-plan-jobs",
        json={
            "asset_ids": [asset_id],
            "platform": "亚马逊",
            "market": "美国",
            "language": "英文",
            "product_info": "",
            "selected_modules": ["商品主视觉"],
            "output_targets": [
                {"mode": "detail", "aspect_ratio": "1:1"},
                {"mode": "amazon_aplus_standard", "aspect_ratio": "970:600"},
            ],
            "dry_run": True,
        },
    )

    assert response.status_code == 422
    assert "每次只能选择一个" in response.text


def test_aplus_rejects_amazon_a_plus_targets_for_non_amazon_platform(client) -> None:
    asset_id = upload_asset(client)
    response = client.post(
        "/api/v1/aplus-plan-jobs",
        json={
            "asset_ids": [asset_id],
            "platform": "Temu",
            "market": "美国",
            "language": "英文",
            "product_info": "",
            "selected_modules": ["商品主视觉"],
            "output_targets": [{"mode": "amazon_aplus_standard", "aspect_ratio": "970:600"}],
            "dry_run": True,
        },
    )
    assert response.status_code == 422
    assert "只支持亚马逊平台" in response.text


def test_aplus_rejects_legacy_module_names_and_total_over_limit(client) -> None:
    asset_id = upload_asset(client)
    legacy_response = client.post(
        "/api/v1/aplus-plan-jobs",
        json={
            "asset_ids": [asset_id],
            "platform": "亚马逊",
            "market": "美国",
            "language": "英文",
            "product_info": "",
            "selected_modules": ["首屏主视觉"],
            "output_targets": [{"mode": "detail", "aspect_ratio": "1:1"}],
            "dry_run": True,
        },
    )
    assert legacy_response.status_code == 422
    assert "不支持的详情页模块" in legacy_response.text

    total_response = client.post(
        "/api/v1/aplus-plan-jobs",
        json={
            "asset_ids": [asset_id],
            "platform": "亚马逊",
            "market": "美国",
            "language": "英文",
            "product_info": "",
            "module_selections": [
                {"name": "商品主视觉", "count": 7},
                {"name": "卖点拆解", "count": 6},
            ],
            "output_targets": [{"mode": "detail", "aspect_ratio": "1:1"}],
            "dry_run": True,
        },
    )
    assert total_response.status_code == 422
    assert "最多生成 12 张" in total_response.text


def test_video_dryrun_creates_one_item_per_selected_type(client) -> None:
    asset_id = upload_asset(client)
    response = client.post(
        "/api/v1/video-jobs",
        json={
            "asset_ids": [asset_id],
            "platform": "TikTok",
            "market": "北美",
            "country": "美国",
            "language": "英语",
            "aspect_ratio": "9:16",
            "selling_points": "便携、防漏、适合通勤",
            "video_types": ["UGC 种草", "痛点解决"],
            "dry_run": True,
        },
    )
    assert response.status_code == 201, response.text
    detail = client.get(f"/api/v1/video-jobs/{response.json()['id']}").json()

    assert detail["status"] == "succeeded"
    assert detail["progress"] == 100
    assert all(item["versions"][0]["url"] == "/demo/video-skincare-result.png" for item in detail["items"])
    assert all("tumbler" not in item["versions"][0]["url"] for item in detail["items"])
    assert [item["video_type"] for item in detail["items"]] == ["UGC 种草", "痛点解决"]
    assert all(item["status"] == "succeeded" for item in detail["items"])
    assert all(item["script_markdown"].startswith("# 15 秒电商短视频脚本") for item in detail["items"])


def test_video_dryrun_edit_creates_child_version(client) -> None:
    asset_id = upload_asset(client)
    job = client.post(
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
    ).json()
    detail = client.get(f"/api/v1/video-jobs/{job['id']}").json()
    item = detail["items"][0]
    first_version = item["versions"][0]

    response = client.post(
        f"/api/v1/video-items/{item['id']}/versions",
        json={"instruction": "节奏更快，结尾加强产品定格"},
    )
    assert response.status_code == 201, response.text
    child = response.json()

    assert child["version_no"] == 2
    assert child["parent_version_id"] == first_version["id"]
    assert child["url"] != first_version["url"]

    updated = client.get(f"/api/v1/video-jobs/{job['id']}").json()
    updated_item = updated["items"][0]
    assert updated_item["current_version_id"] == child["id"]
    assert updated_item["versions"][-1]["instruction"] == "节奏更快，结尾加强产品定格"
    assert "Secondary edit instruction" in updated_item["script_markdown"]


def test_video_edit_rejects_missing_item_and_current_version(client) -> None:
    missing = client.post("/api/v1/video-items/not-found/versions", json={"instruction": "节奏更快"})
    assert missing.status_code == 404

    asset_id = upload_asset(client)
    job = client.post(
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
    ).json()
    detail = client.get(f"/api/v1/video-jobs/{job['id']}").json()
    item_id = detail["items"][0]["id"]
    with client.app.state.session_factory() as session:
        item = session.get(VideoItem, item_id)
        item.current_version_id = None
        session.commit()

    response = client.post(f"/api/v1/video-items/{item_id}/versions", json={"instruction": "节奏更快"})
    assert response.status_code == 422
    assert "Current video version is unavailable" in response.text


def test_video_live_rejects_missing_public_asset_base_url_after_provider_checks(client) -> None:
    asset_id = upload_asset(client)
    session_factory = client.app.state.session_factory
    cipher = client.app.state.cipher
    with session_factory() as session:
        providers = session.scalars(select(Provider)).all()
        for provider in providers:
            if provider.capability in {"llm", "video"}:
                provider.enabled = True
                provider.encrypted_api_key = cipher.encrypt("sk-test")
        session.commit()

    response = client.post(
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
            "dry_run": False,
        },
    )

    assert response.status_code == 409
    assert "PUBLIC_ASSET_BASE_URL" in response.json()["detail"]


def test_dryrun_edit_creates_child_version_and_keeps_original(client) -> None:
    asset_id = upload_asset(client)
    job = client.post(
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
    ).json()
    detail = client.get(f"/api/v1/generation-jobs/{job['id']}").json()
    item = detail["items"][0]
    first_version = item["versions"][0]

    response = client.post(
        f"/api/v1/generation-items/{item['id']}/versions",
        json={"instruction": "背景改为更明亮的淡紫色，产品不变"},
    )
    assert response.status_code == 201, response.text
    child = response.json()

    assert child["version_no"] == 2
    assert child["parent_version_id"] == first_version["id"]
    assert child["url"] != first_version["url"]

    ocr = client.post(f"/api/v1/generation-items/{item['id']}/text-ocr")
    assert ocr.status_code == 200, ocr.text
    assert "lines" in ocr.json()
    unchanged = client.post(
        f"/api/v1/generation-items/{item['id']}/text-versions",
        json={"lines": [{"id": "manual-1", "index": 0, "original_text": "Same", "text": "Same"}]},
    )
    assert unchanged.status_code == 422
    text_edit = client.post(
        f"/api/v1/generation-items/{item['id']}/text-versions",
        json={"lines": [{"id": "manual-1", "index": 0, "original_text": "Old title", "text": "New title"}]},
    )
    assert text_edit.status_code == 201, text_edit.text
    assert text_edit.json()["version_no"] == 3
    assert text_edit.json()["parent_version_id"] == child["id"]


def test_suite_version_endpoint_accepts_empty_instruction_for_regenerate(client) -> None:
    asset_id = upload_asset(client)
    job = client.post(
        "/api/v1/generation-jobs",
        json={
            "asset_ids": [asset_id],
            "platform": "Amazon",
            "market": "United States",
            "language": "English",
            "aspect_ratio": "1:1",
            "selling_points": "Insulated tumbler",
            "mode": "smart",
            "count": 7,
            "dry_run": True,
        },
    ).json()
    detail = client.get(f"/api/v1/generation-jobs/{job['id']}").json()
    item = detail["items"][0]
    first_version = item["versions"][0]

    response = client.post(
        f"/api/v1/generation-items/{item['id']}/versions",
        json={"instruction": ""},
    )

    assert response.status_code == 201, response.text
    child = response.json()
    assert child["version_no"] == 2
    assert child["parent_version_id"] == first_version["id"]
    assert child["instruction"] == ""


def test_validation_rejects_seven_uploads(client) -> None:
    asset_ids = [upload_asset(client) for _ in range(7)]
    response = client.post(
        "/api/v1/generation-jobs",
        json={
            "asset_ids": asset_ids,
            "platform": "Amazon",
            "market": "美国",
            "language": "English",
            "aspect_ratio": "2:3",
            "selling_points": "测试",
            "mode": "smart",
            "count": 7,
            "dry_run": True,
        },
    )
    assert response.status_code == 422


def test_validation_accepts_six_product_images_for_all_single_surfaces(client) -> None:
    asset_ids = [upload_asset(client) for _ in range(6)]
    aplus_module = next(iter(A_PLUS_MODULES))
    video_type = next(iter(VIDEO_TYPES))

    suite_payload = {
        "asset_ids": asset_ids,
        "platform": "Amazon",
        "market": "United States",
        "language": "English",
        "aspect_ratio": "2:3",
        "selling_points": "Test selling points",
        "mode": "smart",
        "count": 7,
        "dry_run": True,
    }
    response = client.post("/api/v1/generation-jobs", json=suite_payload)
    assert response.status_code == 201, response.text

    invalid_count = client.post("/api/v1/generation-jobs", json={**suite_payload, "asset_ids": [asset_ids[0]], "count": 6})
    assert invalid_count.status_code == 422

    aplus = client.post(
        "/api/v1/aplus-plan-jobs",
        json={
            "asset_ids": asset_ids,
            "platform": "Amazon",
            "market": "United States",
            "language": "English",
            "product_info": "Test product info",
            "module_selections": [{"name": aplus_module, "count": 1}],
            "output_targets": [{"mode": "detail", "aspect_ratio": "1:1"}],
            "dry_run": True,
        },
    )
    assert aplus.status_code == 201, aplus.text

    video_payload = {
        "asset_ids": asset_ids,
        "platform": "TikTok",
        "market": "North America",
        "country": "United States",
        "language": "English",
        "aspect_ratio": "9:16",
        "selling_points": "Portable product",
        "video_types": [video_type],
        "dry_run": True,
    }
    video = client.post("/api/v1/video-jobs", json=video_payload)
    assert video.status_code == 201, video.text

    video_assist = client.post("/api/v1/video-copywriting-assist", json=video_payload)
    assert video_assist.status_code == 200, video_assist.text


def test_custom_counts_drive_dryrun_plan_and_are_limited_to_four_each(client) -> None:
    asset_id = upload_asset(client)
    payload = {
        "asset_ids": [asset_id],
        "platform": "亚马逊",
        "market": "美国",
        "language": "英语",
        "aspect_ratio": "1:1",
        "selling_points": "双层保温，防滑握持，通勤便携",
        "mode": "custom",
        "count": 7,
        "custom_counts": {
            "white_background": 1,
            "scene": 2,
            "selling_point": 2,
            "other": 2,
        },
        "model_preference": "fidelity",
        "dry_run": True,
    }

    response = client.post("/api/v1/generation-jobs", json=payload)

    assert response.status_code == 201, response.text
    detail = client.get(f"/api/v1/generation-jobs/{response.json()['id']}").json()
    assert [item["image_type"].split(" ")[0] for item in detail["items"]] == [
        "白底图",
        "场景图",
        "场景图",
        "卖点图",
        "卖点图",
        "其他图",
        "其他图",
    ]
    assert detail["params"]["custom_counts"] == payload["custom_counts"]
    assert detail["params"]["model_preference"] == "fidelity"

    too_many = {**payload, "count": 10, "custom_counts": {**payload["custom_counts"], "scene": 5}}
    invalid = client.post("/api/v1/generation-jobs", json=too_many)
    assert invalid.status_code == 422


def test_ai_copywriting_dryrun_uses_backend_prompted_flow(client) -> None:
    response = client.post(
        "/api/v1/copywriting-assist",
        json={
            "platform": "淘宝/天猫",
            "market": "中国大陆",
            "language": "简体中文",
            "selling_points": "保温杯，防滑",
            "dry_run": True,
        },
    )

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["dry_run"] is True
    assert result["provider_code"] is None
    assert "保温杯" in result["selling_points"]
    assert "### 1. 商品定位" in result["selling_points"]
    assert "### 2. 适用场景" in result["selling_points"]
    assert "### 3. 5大核心卖点" in result["selling_points"]
    assert "淘宝/天猫" not in result["selling_points"]


def test_ai_copywriting_rejects_unsafe_input_text_before_generation(client) -> None:
    response = client.post(
        "/api/v1/copywriting-assist",
        json={
            "platform": "亚马逊",
            "market": "美国",
            "language": "英文",
            "selling_points": "使用习近平照片做宣传",
            "dry_run": True,
        },
    )

    assert response.status_code == 422
    assert "输入内容安全拦截" in response.json()["detail"]


def test_ai_copywriting_live_prompt_separates_image_language_from_output_language() -> None:
    prompt = build_copywriting_user_prompt(
        CopywritingAssistCreate(
            platform="亚马逊",
            market="美国",
            language="英文",
            selling_points="保温杯，防滑",
            dry_run=False,
        )
    )
    data = json.loads(prompt)

    assert data["output_language"] == "简体中文"
    assert data["image_text_language"] == "英文"
    assert data["input_mode"] == "image_with_text"
    assert "language" not in data
    assert "必须使用简体中文" in data["instruction"]

    image_only = json.loads(
        build_copywriting_user_prompt(
            CopywritingAssistCreate(platform="亚马逊", market="美国", language="英文", selling_points="")
        )
    )
    assert image_only["input_mode"] == "image_only"


def test_generation_job_accepts_structured_product_and_brand_inputs(client) -> None:
    asset_id = upload_asset(client)
    response = client.post(
        "/api/v1/generation-jobs",
        json={
            "asset_ids": [asset_id],
            "platform": "亚马逊",
            "market": "美国",
            "language": "英语",
            "aspect_ratio": "2:3",
            "selling_points": "双层保温",
            "product_name": "通勤保温杯",
            "category": "饮水器具",
            "specifications": "500ml",
            "sku_info": "白色单品",
            "accessories": "杯盖",
            "certifications": "未提供",
            "target_audience": "通勤人群",
            "brand_style": "克制、现代、蓝灰色",
            "mode": "smart",
            "count": 8,
            "model_preference": "fidelity",
            "dry_run": True,
        },
    )
    assert response.status_code == 201, response.text
    job = response.json()
    assert job["params"]["product_name"] == "通勤保温杯"
    assert job["params"]["aspect_ratio"] == "2:3"
    assert job["count"] == 8


def test_generation_job_rejects_unsafe_input_text_before_job_creation(client) -> None:
    asset_id = upload_asset(client)
    response = client.post(
        "/api/v1/generation-jobs",
        json={
            "asset_ids": [asset_id],
            "platform": "亚马逊",
            "market": "美国",
            "language": "英文",
            "aspect_ratio": "1:1",
            "selling_points": "宣传赌博博彩玩法",
            "mode": "smart",
            "count": 7,
            "dry_run": True,
        },
    )

    assert response.status_code == 422
    assert "输入内容安全拦截" in response.json()["detail"]


def test_dryrun_executes_the_extended_prompt_workflow_without_external_calls(client) -> None:
    asset_id = upload_asset(client)
    response = client.post(
        "/api/v1/generation-jobs",
        json={
            "asset_ids": [asset_id], "platform": "亚马逊", "market": "美国", "language": "无文字",
            "aspect_ratio": "4:5", "selling_points": "双层保温", "brand_style": "现代克制",
            "mode": "smart", "count": 7, "model_preference": "fidelity", "dry_run": True,
        },
    )
    assert response.status_code == 201, response.text
    detail = client.get(f"/api/v1/generation-jobs/{response.json()['id']}").json()
    assert set(detail["params"]["_prompt_versions"]) == {
        "product-vision", "copywriting-assist", "edit-rewrite", "image-text-edit", "content-safety-review"
    }
    logs = client.get("/api/v1/admin/logs", params={"job_id": detail["id"], "page_size": 100}).json()["items"]
    nodes = {log["node"] for log in logs}
    assert {"product_vision", "meta_prompt", "semantic_validator", "image_generate", "aggregate"}.issubset(nodes)
    assert "image_qa" not in nodes
