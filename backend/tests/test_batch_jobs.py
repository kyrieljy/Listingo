from __future__ import annotations

import asyncio
from io import BytesIO
from zipfile import ZipFile

from PIL import Image

from backend.app.models import BatchItem, BatchJob, GenerationJob


def make_png() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (640, 640), "#f2ede4").save(buffer, format="PNG")
    return buffer.getvalue()


def upload_asset_payload(client) -> dict:
    response = client.post(
        "/api/v1/assets",
        files={"file": ("product.png", make_png(), "image/png")},
    )
    assert response.status_code == 201, response.text
    return response.json()


def upload_asset(client) -> str:
    return upload_asset_payload(client)["id"]


def tick_batch_scheduler(client) -> None:
    asyncio.run(client.app.state.batch_scheduler.tick())


def test_workspace_config_exposes_batch_limits_without_secrets(client) -> None:
    payload = client.get("/api/v1/workspace-config").json()

    assert payload["max_batch_tasks"] == client.app.state.settings.max_batch_tasks
    assert payload["max_batch_tasks"] == 100
    assert payload["max_batch_item_assets"] == client.app.state.settings.max_batch_item_assets
    assert payload["max_batch_item_assets"] == 6
    assert "secret" not in payload
    assert "api_key" not in payload


def test_batch_suite_dryrun_runs_items_and_downloads_grouped_zip(client) -> None:
    assets = [upload_asset_payload(client) for _ in range(4)]
    asset_ids = [asset["id"] for asset in assets]
    response = client.post(
        "/api/v1/batch-jobs",
        json={
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
                {"asset_ids": asset_ids[:4], "name": "Pack 01", "selling_points": "通勤背包，耐磨防泼水"},
                {"asset_ids": asset_ids[2:4], "name": "Pack 02", "selling_points": "轻量收纳，适合短途"},
            ],
        },
    )
    assert response.status_code == 201, response.text
    batch_id = response.json()["id"]

    tick_batch_scheduler(client)
    detail = client.get(f"/api/v1/batch-jobs/{batch_id}").json()

    assert detail["status"] == "succeeded"
    assert detail["completed_count"] == 2
    assert detail["progress"] == 100
    assert all(item["generation_job_id"] for item in detail["items"])
    assert all(item["generation_job"]["status"] == "succeeded" for item in detail["items"])
    assert detail["items"][0]["thumbnail_url"] == assets[0]["url"]
    assert detail["items"][1]["thumbnail_url"] == assets[2]["url"]
    assert all(item["completed_image_count"] == 7 for item in detail["items"])
    assert all(item["failed_image_count"] == 0 for item in detail["items"])
    assert all(item["total_image_count"] == 7 for item in detail["items"])
    suite_history_ids = {job["id"] for job in client.get("/api/v1/generation-jobs").json()}
    assert not suite_history_ids.intersection({item["generation_job_id"] for item in detail["items"]})

    first_batch_item = detail["items"][0]
    first_result_item = first_batch_item["generation_job"]["items"][0]
    selected_archive = client.get(
        "/api/v1/batch-jobs/selection-download",
        params={
            "business_type": "suite",
            "batch_item_ids": first_batch_item["id"],
            "item_ids": first_result_item["id"],
        },
    )
    assert selected_archive.status_code == 200
    with ZipFile(BytesIO(selected_archive.content)) as zip_file:
        selected_names = zip_file.namelist()
    assert len(selected_names) == 1
    assert "Pack 01" in selected_names[0]
    assert "Pack 02" not in selected_names[0]

    archive = client.get(f"/api/v1/batch-jobs/{batch_id}/download")
    assert archive.status_code == 200
    assert archive.headers["content-type"] == "application/zip"
    with ZipFile(BytesIO(archive.content)) as zip_file:
        names = zip_file.namelist()
        watermarked_bytes = zip_file.read(names[0])
    assert any(name.startswith("商品任务01-Pack 01/01-") for name in names)
    assert any(name.startswith("商品任务02-Pack 02/01-") for name in names)

    plain_archive = client.get(f"/api/v1/batch-jobs/{batch_id}/download", params={"include_watermark": False})
    assert plain_archive.status_code == 200
    with ZipFile(BytesIO(plain_archive.content)) as zip_file:
        plain_bytes = zip_file.read(zip_file.namelist()[0])
    assert watermarked_bytes != plain_bytes


def test_batch_aplus_dryrun_runs_plan_and_generation_chain(client) -> None:
    asset = upload_asset_payload(client)
    asset_id = asset["id"]
    response = client.post(
        "/api/v1/batch-jobs",
        json={
            "business_type": "aplus",
            "global_params": {
                "platform": "亚马逊",
                "market": "美国",
                "language": "英文",
                "module_selections": [{"name": "商品主视觉", "count": 1}],
                "output_targets": [{"mode": "detail", "aspect_ratio": "1:1"}],
                "dry_run": True,
            },
            "items": [{"asset_ids": [asset_id], "name": "Outdoor pack", "selling_points": "容量大，分区清晰"}],
        },
    )
    assert response.status_code == 201, response.text
    batch_id = response.json()["id"]

    tick_batch_scheduler(client)
    detail = client.get(f"/api/v1/batch-jobs/{batch_id}").json()

    item = detail["items"][0]
    assert detail["status"] == "succeeded"
    assert item["aplus_plan_job_id"]
    assert item["aplus_generation_job_id"]
    assert item["aplus_plan_job"]["status"] == "succeeded"
    assert item["aplus_generation_job"]["status"] == "succeeded"
    assert item["thumbnail_url"] == asset["url"]
    assert item["completed_image_count"] == 1
    assert item["failed_image_count"] == 0
    assert item["total_image_count"] == 1
    aplus_history_ids = {job["id"] for job in client.get("/api/v1/aplus-generation-jobs").json()}
    assert item["aplus_generation_job_id"] not in aplus_history_ids


def test_batch_limits_cancel_and_retry_are_database_driven(client) -> None:
    asset_id = upload_asset(client)
    too_many = client.post(
        "/api/v1/batch-jobs",
        json={
            "business_type": "suite",
            "global_params": {"platform": "Amazon", "market": "美国", "language": "English", "aspect_ratio": "1:1", "dry_run": True},
            "items": [
                {"asset_ids": [asset_id], "name": f"Item {index}", "selling_points": "卖点"}
                for index in range(client.app.state.settings.max_batch_tasks + 1)
            ],
        },
    )
    assert too_many.status_code == 422

    response = client.post(
        "/api/v1/batch-jobs",
        json={
            "business_type": "suite",
            "global_params": {"platform": "Amazon", "market": "美国", "language": "English", "aspect_ratio": "1:1", "dry_run": True},
            "items": [{"asset_ids": [asset_id], "name": "Retry me", "selling_points": "卖点"}],
        },
    )
    assert response.status_code == 201, response.text
    batch_id = response.json()["id"]

    cancelled = client.post(f"/api/v1/batch-jobs/{batch_id}/cancel").json()
    assert cancelled["status"] == "cancelled"
    assert cancelled["items"][0]["status"] == "cancelled"

    with client.app.state.session_factory() as session:
        batch = session.get(BatchJob, batch_id)
        item = session.get(BatchItem, batch.items[0].id)
        child = session.get(GenerationJob, item.generation_job_id)
        batch.status = "partial_failed"
        item.status = "failed"
        item.error = "simulated"
        child.status = "failed"
        child.error = "simulated"
        session.commit()

    retried = client.post(f"/api/v1/batch-jobs/{batch_id}/retry-failed").json()
    assert retried["status"] == "queued"
    assert retried["items"][0]["status"] == "queued"


def test_batch_validation_fixtures_create_real_dryrun_history(client) -> None:
    suite_response = client.post("/api/v1/batch-jobs/validation-fixtures", json={"business_type": "suite"})
    assert suite_response.status_code == 201, suite_response.text
    suite_jobs = suite_response.json()
    assert len(suite_jobs) == 2
    assert all(job["business_type"] == "suite" for job in suite_jobs)
    assert all(job["notification_config"]["validation_fixture"] is True for job in suite_jobs)
    assert suite_jobs[0]["status"] == "succeeded"
    assert suite_jobs[1]["status"] == "partial_failed"
    assert suite_jobs[1]["items"][-1]["failed_image_count"] == 1
    assert suite_jobs[1]["items"][-1]["completed_image_count"] == 6

    aplus_response = client.post("/api/v1/batch-jobs/validation-fixtures", json={"business_type": "aplus"})
    assert aplus_response.status_code == 201, aplus_response.text
    aplus_jobs = aplus_response.json()
    assert len(aplus_jobs) == 2
    assert all(job["business_type"] == "aplus" for job in aplus_jobs)
    assert aplus_jobs[0]["status"] == "succeeded"
    assert aplus_jobs[1]["status"] == "partial_failed"
    assert aplus_jobs[1]["items"][-1]["failed_image_count"] == 1
    assert aplus_jobs[1]["items"][-1]["completed_image_count"] == 1
