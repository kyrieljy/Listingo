from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from backend.app.config import Settings
from backend.app.core.runtime import RuntimeStateService, default_runtime
from backend.app.core.storage.keys import batch_status_key
from backend.app.models import (
    Asset,
    AplusItem,
    AplusJob,
    AplusVersion,
    BatchItem,
    BatchJob,
    GenerationItem,
    GenerationJob,
    GenerationVersion,
    utcnow,
)
from backend.app.schemas import (
    AplusGenerationJobCreate,
    AplusPlanJobCreate,
    BatchJobCreate,
    GenerationJobCreate,
)
from backend.app.services.aplus_jobs import cancel_aplus_job, serialize_aplus_job
from backend.app.services.job_creation import (
    TaskCreationError,
    create_aplus_generation_job_record,
    create_aplus_plan_job_record,
    create_generation_job_record,
)
from backend.app.services.jobs import cancel_generation_job
from backend.app.services.subscriptions import confirm_quota, release_quota
from backend.app.services.watermarking import apply_ai_watermark


AMAZON = "\u4e9a\u9a6c\u900a"
US_MARKET = "\u7f8e\u56fd"
ENGLISH = "\u82f1\u6587"
TASK_DIR_PREFIX = "\u5546\u54c1\u4efb\u52a1"

FINAL_STATUSES = {"succeeded", "partial_failed", "failed", "cancelled", "partial_cancelled"}
FAILED_STATUSES = {"failed", "partial_failed"}
CANCELLED_STATUSES = {"cancelled", "partial_cancelled"}
DEMO_ASSET_DIR = Path(__file__).resolve().parents[1] / "static" / "demo"
SUITE_FIXTURE_ASSETS = [
    DEMO_ASSET_DIR / "tumbler-source.png",
    DEMO_ASSET_DIR / "tumbler-feature.png",
    DEMO_ASSET_DIR / "tumbler-lifestyle.png",
    DEMO_ASSET_DIR / "tumbler-commute.png",
]
APLUS_FIXTURE_ASSETS = [
    DEMO_ASSET_DIR / "aplus-outdoor-module-01.png",
    DEMO_ASSET_DIR / "aplus-outdoor-module-02.png",
    DEMO_ASSET_DIR / "aplus-outdoor-module-03.png",
    DEMO_ASSET_DIR / "aplus-outdoor-module-04.png",
]


@dataclass(frozen=True)
class BatchExportEntry:
    folder: str
    label: str
    file_path: str
    version_id: str


def _json_loads(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


def _compact_dict(data: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if value is not None}


def _suite_params(global_params: dict[str, Any], item: Any) -> dict[str, Any]:
    overrides = dict(item.overrides or {})
    params = {
        "platform": AMAZON,
        "market": US_MARKET,
        "language": ENGLISH,
        "aspect_ratio": "1:1",
        "selling_points": "",
        "product_name": "",
        "category": "",
        "specifications": "",
        "sku_info": "",
        "accessories": "",
        "certifications": "",
        "target_audience": "",
        "brand_style": "",
        "mode": "smart",
        "count": 7,
        "custom_counts": None,
        "model_preference": "fidelity",
        "dry_run": True,
    }
    params.update(global_params or {})
    params.update(overrides)
    if params.get("ratio") and not params.get("aspect_ratio"):
        params["aspect_ratio"] = params["ratio"]
    params["asset_ids"] = item.asset_ids
    params["product_name"] = item.name or params.get("product_name") or ""
    params["selling_points"] = item.selling_points or params.get("selling_points") or params["product_name"]
    return _compact_dict(params)


def _aplus_params(global_params: dict[str, Any], item: Any) -> dict[str, Any]:
    overrides = dict(item.overrides or {})
    params = {
        "platform": AMAZON,
        "market": US_MARKET,
        "language": ENGLISH,
        "module_selections": [{"name": "\u5546\u54c1\u4e3b\u89c6\u89c9", "count": 1}],
        "selected_modules": None,
        "output_targets": [{"mode": "detail", "aspect_ratio": "1:1"}],
        "dry_run": True,
    }
    params.update(global_params or {})
    params.update(overrides)
    if not params.get("output_targets"):
        params["output_targets"] = [{"mode": "detail", "aspect_ratio": params.get("aspect_ratio") or "1:1"}]
    product_info = params.get("product_info") or ""
    parts = []
    if item.name:
        parts.append(f"Product name: {item.name}")
    if item.selling_points:
        parts.append(f"Selling points: {item.selling_points}")
    params["product_info"] = product_info or "\n".join(parts)
    params["asset_ids"] = item.asset_ids
    return _compact_dict(params)


def create_batch_job_record(
    session: Session,
    payload: BatchJobCreate,
    settings: Settings,
    *,
    user_id: str | None = None,
) -> BatchJob:
    if len(payload.items) > settings.max_batch_tasks:
        raise TaskCreationError(422, f"A batch can contain at most {settings.max_batch_tasks} products")

    batch = BatchJob(
        user_id=user_id,
        business_type=payload.business_type,
        status="queued",
        global_params_json=json.dumps(payload.global_params, ensure_ascii=False),
        total_count=len(payload.items),
        completed_count=0,
        failed_count=0,
        progress=0,
        notification_config_json=json.dumps(payload.notification_config, ensure_ascii=False),
    )
    session.add(batch)
    session.flush()

    for index, item in enumerate(payload.items, start=1):
        if len(item.asset_ids) > settings.max_batch_item_assets:
            raise TaskCreationError(422, f"Each batch product can contain at most {settings.max_batch_item_assets} images")
        if payload.business_type == "suite":
            params = _suite_params(payload.global_params, item)
            child_payload = GenerationJobCreate(**params)
            child_job = create_generation_job_record(
                session,
                child_payload,
                max_asset_count=settings.max_batch_item_assets,
                user_id=user_id,
            )
            batch_item = BatchItem(
                batch_job_id=batch.id,
                index=index,
                name=item.name or child_payload.product_name or f"Task {index:02d}",
                status="queued",
                params_json=json.dumps(child_payload.model_dump(), ensure_ascii=False),
                asset_ids_json=json.dumps(item.asset_ids),
                generation_job_id=child_job.id,
            )
        else:
            params = _aplus_params(payload.global_params, item)
            child_payload = AplusPlanJobCreate(**params)
            child_job = create_aplus_plan_job_record(
                session,
                child_payload,
                max_asset_count=settings.max_batch_item_assets,
                user_id=user_id,
            )
            batch_item = BatchItem(
                batch_job_id=batch.id,
                index=index,
                name=item.name or f"Task {index:02d}",
                status="queued",
                params_json=json.dumps(child_payload.model_dump(), ensure_ascii=False),
                asset_ids_json=json.dumps(item.asset_ids),
                aplus_plan_job_id=child_job.id,
            )
        session.add(batch_item)
    session.flush()
    return batch


def load_batch_job(session: Session, batch_id: str) -> BatchJob | None:
    return session.scalar(
        select(BatchJob)
        .where(BatchJob.id == batch_id)
        .options(selectinload(BatchJob.items))
    )


def _serialize_generation_version(version: GenerationVersion) -> dict[str, Any]:
    return {
        "id": version.id,
        "parent_version_id": version.parent_version_id,
        "version_no": version.version_no,
        "instruction": version.instruction,
        "url": version.url,
        "created_at": version.created_at,
    }


def _serialize_generation_job(job: GenerationJob | None) -> dict[str, Any] | None:
    if not job:
        return None
    return {
        "id": job.id,
        "status": job.status,
        "dry_run": job.dry_run,
        "progress": job.progress,
        "count": job.count,
        "params": _json_loads(job.params_json, {}),
        "error": job.error,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "completed_at": job.completed_at,
        "items": [
            {
                "id": item.id,
                "index": item.index,
                "route_symbol": item.route_symbol,
                "image_type": item.image_type,
                "prompt_text": item.prompt_text,
                "status": item.status,
                "provider_id": item.provider_id,
                "provider_task_id": item.provider_task_id,
                "error": item.error,
                "current_version_id": item.current_version_id,
                "versions": [_serialize_generation_version(version) for version in item.versions],
            }
            for item in job.items
        ],
    }


def _load_generation_job(session: Session, job_id: str | None) -> GenerationJob | None:
    if not job_id:
        return None
    return session.scalar(
        select(GenerationJob)
        .where(GenerationJob.id == job_id)
        .options(selectinload(GenerationJob.items).selectinload(GenerationItem.versions))
    )


def _load_aplus_job(session: Session, job_id: str | None) -> AplusJob | None:
    if not job_id:
        return None
    return session.scalar(
        select(AplusJob)
        .where(AplusJob.id == job_id)
        .options(selectinload(AplusJob.items).selectinload(AplusItem.versions))
    )


def _first_asset_url(session: Session, asset_ids: list[str]) -> str | None:
    if not asset_ids:
        return None
    asset = session.get(Asset, asset_ids[0])
    return asset.url if asset else None


def _generation_image_counts(job: GenerationJob | None) -> tuple[int, int, int]:
    if not job:
        return (0, 0, 0)
    completed = sum(1 for item in job.items if item.status == "succeeded")
    failed = sum(1 for item in job.items if item.status == "failed")
    return (completed, failed, max(job.count, len(job.items)))


def _aplus_image_counts(job: AplusJob | None) -> tuple[int, int, int]:
    if not job:
        return (0, 0, 0)
    completed = sum(1 for item in job.items if item.status == "succeeded")
    failed = sum(1 for item in job.items if item.status == "failed")
    return (completed, failed, max(job.count, len(job.items)))


def _batch_item_media_summary(
    session: Session,
    item: BatchItem,
    generation_job: GenerationJob | None,
    aplus_generation_job: AplusJob | None,
) -> dict[str, Any]:
    asset_ids = _json_loads(item.asset_ids_json, [])
    thumbnail = _first_asset_url(session, asset_ids)
    if item.generation_job_id:
        completed, failed, total = _generation_image_counts(generation_job)
    else:
        completed, failed, total = _aplus_image_counts(aplus_generation_job)
    return {
        "thumbnail_url": thumbnail,
        "completed_image_count": completed,
        "failed_image_count": failed,
        "total_image_count": total,
    }


def child_progress(session: Session, item: BatchItem) -> int:
    if item.generation_job_id:
        job = session.get(GenerationJob, item.generation_job_id)
        return int(job.progress) if job else 0
    if item.aplus_generation_job_id:
        job = session.get(AplusJob, item.aplus_generation_job_id)
        return int(job.progress) if job else 0
    if item.aplus_plan_job_id:
        job = session.get(AplusJob, item.aplus_plan_job_id)
        return 50 if job and job.status == "succeeded" else int((job.progress if job else 0) * 0.5)
    return 100 if item.status in FINAL_STATUSES else 0


def aggregate_batch_job(session: Session, batch: BatchJob) -> BatchJob:
    items = list(batch.items)
    if not items:
        batch.status = "failed"
        batch.error = "Batch has no items"
        batch.progress = 100
        batch.completed_at = utcnow()
        sync_batch_quota(session, batch)
        return batch

    batch.completed_count = sum(1 for item in items if item.status == "succeeded")
    batch.failed_count = sum(1 for item in items if item.status in FAILED_STATUSES)
    batch.progress = round(sum(child_progress(session, item) for item in items) / len(items))
    statuses = [item.status for item in items]
    active = any(status in {"queued", "running", "cancelling"} for status in statuses)
    if batch.status == "cancelling" and active:
        batch.status = "cancelling"
    elif active:
        batch.status = "running" if any(status == "running" for status in statuses) else "queued"
        batch.completed_at = None
    elif all(status == "succeeded" for status in statuses):
        batch.status = "succeeded"
        batch.progress = 100
        batch.completed_at = utcnow()
    elif all(status in CANCELLED_STATUSES for status in statuses):
        batch.status = "cancelled"
        batch.progress = 100
        batch.completed_at = utcnow()
    elif any(status in CANCELLED_STATUSES for status in statuses):
        batch.status = "partial_cancelled"
        batch.progress = 100
        batch.completed_at = utcnow()
    elif any(status in FAILED_STATUSES for status in statuses):
        batch.status = "failed" if batch.completed_count == 0 else "partial_failed"
        batch.progress = 100
        batch.completed_at = utcnow()
    sync_batch_quota(session, batch)
    return batch


def sync_batch_quota(session: Session, batch: BatchJob) -> None:
    if batch.status in {"succeeded", "partial_failed"}:
        confirm_quota(session, ref_type="batch_job", ref_id=batch.id)
    elif batch.status in {"failed", "cancelled", "partial_cancelled"}:
        release_quota(session, ref_type="batch_job", ref_id=batch.id)


def sync_batch_item_from_children(session: Session, item: BatchItem) -> BatchItem:
    if item.generation_job_id:
        job = session.get(GenerationJob, item.generation_job_id)
        if job and job.status in FINAL_STATUSES:
            item.status = job.status
            item.error = job.error
            item.completed_at = job.completed_at or utcnow()
        return item

    if item.aplus_plan_job_id and not item.aplus_generation_job_id:
        plan_job = session.get(AplusJob, item.aplus_plan_job_id)
        if plan_job and plan_job.status == "failed":
            item.status = "failed"
            item.error = plan_job.error
            item.completed_at = plan_job.completed_at or utcnow()
        return item

    if item.aplus_generation_job_id:
        job = session.get(AplusJob, item.aplus_generation_job_id)
        if job and job.status in FINAL_STATUSES:
            item.status = job.status
            item.error = job.error
            item.completed_at = job.completed_at or utcnow()
    return item


def serialize_batch_job(session: Session, batch: BatchJob, *, include_children: bool = True) -> dict[str, Any]:
    serialized_items = []
    for item in batch.items:
        loaded_generation_job = _load_generation_job(session, item.generation_job_id) if item.generation_job_id else None
        generation_job = loaded_generation_job if include_children else None
        aplus_plan_job = _load_aplus_job(session, item.aplus_plan_job_id) if include_children else None
        loaded_aplus_generation_job = _load_aplus_job(session, item.aplus_generation_job_id) if item.aplus_generation_job_id else None
        aplus_generation_job = loaded_aplus_generation_job if include_children else None
        summary = _batch_item_media_summary(session, item, loaded_generation_job, loaded_aplus_generation_job)
        serialized_items.append(
            {
                "id": item.id,
                "index": item.index,
                "name": item.name,
                "status": item.status,
                **summary,
                "params": _json_loads(item.params_json, {}),
                "asset_ids": _json_loads(item.asset_ids_json, []),
                "generation_job_id": item.generation_job_id,
                "aplus_plan_job_id": item.aplus_plan_job_id,
                "aplus_generation_job_id": item.aplus_generation_job_id,
                "error": item.error,
                "started_at": item.started_at,
                "completed_at": item.completed_at,
                "generation_job": _serialize_generation_job(generation_job),
                "aplus_plan_job": serialize_aplus_job(aplus_plan_job) if aplus_plan_job else None,
                "aplus_generation_job": serialize_aplus_job(aplus_generation_job) if aplus_generation_job else None,
            }
        )
    return {
        "id": batch.id,
        "user_id": batch.user_id,
        "business_type": batch.business_type,
        "status": batch.status,
        "global_params": _json_loads(batch.global_params_json, {}),
        "total_count": batch.total_count,
        "completed_count": batch.completed_count,
        "failed_count": batch.failed_count,
        "progress": batch.progress,
        "notification_config": _json_loads(batch.notification_config_json, {}),
        "error": batch.error,
        "started_at": batch.started_at,
        "completed_at": batch.completed_at,
        "created_at": batch.created_at,
        "updated_at": batch.updated_at,
        "items": serialized_items,
    }


def invalidate_batch_status(batch_id: str, runtime: RuntimeStateService | None = None) -> None:
    """Drop a mutable progress snapshot after its PostgreSQL facts commit."""
    service = runtime or default_runtime()
    if service is not None:
        service.delete_best_effort(batch_status_key(batch_id))


def cached_batch_job_payload(
    session: Session,
    batch: BatchJob,
    *,
    include_children: bool = True,
    runtime: RuntimeStateService | None = None,
) -> dict[str, Any]:
    service = runtime or default_runtime()
    if service is None:
        return serialize_batch_job(session, batch, include_children=include_children)
    return service.cached(
        batch_status_key(batch.id),
        service.ttls.batch_status,
        lambda: serialize_batch_job(session, batch, include_children=include_children),
    )


def cancel_batch_job(session: Session, batch: BatchJob) -> BatchJob:
    if batch.status in FINAL_STATUSES:
        return batch
    batch.status = "cancelling"
    for item in batch.items:
        if item.status == "queued":
            item.status = "cancelled"
            item.error = "User cancelled batch item"
            item.completed_at = utcnow()
            continue
        if item.status != "running":
            continue
        if item.generation_job_id:
            child = session.get(GenerationJob, item.generation_job_id)
            if child:
                cancel_generation_job(session, child)
        if item.aplus_plan_job_id:
            child = session.get(AplusJob, item.aplus_plan_job_id)
            if child:
                cancel_aplus_job(session, child)
        if item.aplus_generation_job_id:
            child = session.get(AplusJob, item.aplus_generation_job_id)
            if child:
                cancel_aplus_job(session, child)
        sync_batch_item_from_children(session, item)
    aggregate_batch_job(session, batch)
    session.commit()
    session.refresh(batch)
    invalidate_batch_status(batch.id)
    return batch


def retry_failed_batch_job(session: Session, batch: BatchJob) -> BatchJob:
    for item in batch.items:
        if item.status not in FAILED_STATUSES:
            continue
        item.status = "queued"
        item.error = None
        item.started_at = None
        item.completed_at = None
        if item.generation_job_id:
            child = session.get(GenerationJob, item.generation_job_id)
            if child:
                child.status = "queued"
                child.error = None
                child.completed_at = None
        if item.aplus_plan_job_id and not item.aplus_generation_job_id:
            child = session.get(AplusJob, item.aplus_plan_job_id)
            if child:
                child.status = "queued"
                child.error = None
                child.completed_at = None
        if item.aplus_generation_job_id:
            child = session.get(AplusJob, item.aplus_generation_job_id)
            if child:
                child.status = "queued"
                child.error = None
                child.completed_at = None
    batch.status = "queued"
    batch.error = None
    batch.completed_at = None
    aggregate_batch_job(session, batch)
    session.commit()
    session.refresh(batch)
    invalidate_batch_status(batch.id)
    return batch


def create_aplus_generation_for_batch_item(session: Session, item: BatchItem) -> AplusJob:
    if not item.aplus_plan_job_id:
        raise TaskCreationError(500, "A+ batch item is missing plan job")
    plan_job = session.get(AplusJob, item.aplus_plan_job_id)
    if not plan_job or plan_job.status != "succeeded":
        raise TaskCreationError(409, "A+ plan job has not succeeded")
    params = _json_loads(item.params_json, {})
    payload = AplusGenerationJobCreate(
        plan_job_id=plan_job.id,
        module_item_ids=[plan_item.id for plan_item in plan_job.items if plan_item.output_mode == "plan"],
        output_targets=params.get("output_targets") or [{"mode": "detail", "aspect_ratio": "1:1"}],
        dry_run=bool(params.get("dry_run", True)),
    )
    generation_job = create_aplus_generation_job_record(
        session,
        payload,
        prompt_version_id=plan_job.prompt_version_id,
        user_id=plan_job.user_id,
    )
    item.aplus_generation_job_id = generation_job.id
    session.flush()
    return generation_job


def _version_for_generation_item(item: GenerationItem) -> GenerationVersion | None:
    if item.current_version_id:
        return next((version for version in item.versions if version.id == item.current_version_id), None)
    return item.versions[-1] if item.versions else None


def _version_for_aplus_item(item: AplusItem) -> AplusVersion | None:
    if item.current_version_id:
        return next((version for version in item.versions if version.id == item.current_version_id), None)
    return item.versions[-1] if item.versions else None


def _safe_filename(value: str, fallback: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|\r\n]+', "-", value).strip(" .-")
    return (cleaned or fallback)[:80]


def _unique_arcname(used: set[str], arcname: str) -> str:
    if arcname not in used:
        used.add(arcname)
        return arcname
    path = Path(arcname)
    stem = path.stem
    suffix = path.suffix
    parent = path.parent.as_posix()
    counter = 2
    while True:
        candidate = f"{parent}/{stem}-{counter}{suffix}" if parent != "." else f"{stem}-{counter}{suffix}"
        if candidate not in used:
            used.add(candidate)
            return candidate
        counter += 1


def _batch_export_image_path(image_path: str, destination: Path, export_stem: str, include_watermark: bool) -> str:
    if not include_watermark:
        return image_path
    return str(apply_ai_watermark(image_path, destination.parent / "watermarked" / f"{export_stem}.png"))


def _batch_item_folder(batch: BatchJob, item: BatchItem) -> str:
    created = batch.created_at.strftime("%Y-%m-%d %H-%M") if batch.created_at else "batch"
    fallback = f"{TASK_DIR_PREFIX}{item.index:02d}"
    label = _safe_filename(item.name or fallback, fallback)
    return f"{created} {label}"


def _collect_batch_export_entries(
    session: Session,
    *,
    business_type: str,
    batch_item_ids: list[str],
    child_item_ids: set[str],
) -> list[BatchExportEntry]:
    if not batch_item_ids or not child_item_ids:
        return []
    requested_order = {item_id: index for index, item_id in enumerate(batch_item_ids)}
    batch_items = session.scalars(
        select(BatchItem)
        .where(BatchItem.id.in_(batch_item_ids))
        .options(selectinload(BatchItem.batch_job))
    ).all()
    batch_items = sorted(batch_items, key=lambda item: requested_order.get(item.id, 9999))
    entries: list[BatchExportEntry] = []
    for batch_item in batch_items:
        batch = batch_item.batch_job
        if not batch or batch.business_type != business_type:
            continue
        folder = _batch_item_folder(batch, batch_item)
        if business_type == "suite":
            job = _load_generation_job(session, batch_item.generation_job_id)
            if not job:
                continue
            for output_index, generation_item in enumerate(job.items, start=1):
                if generation_item.id not in child_item_ids or generation_item.status != "succeeded":
                    continue
                version = _version_for_generation_item(generation_item)
                if not version or not version.file_path or not Path(version.file_path).exists():
                    continue
                entries.append(
                    BatchExportEntry(
                        folder=folder,
                        label=f"{output_index:02d}-{_safe_filename(generation_item.image_type, 'image')}.png",
                        file_path=version.file_path,
                        version_id=version.id,
                    )
                )
        else:
            job = _load_aplus_job(session, batch_item.aplus_generation_job_id)
            if not job:
                continue
            for output_index, aplus_item in enumerate(job.items, start=1):
                if aplus_item.id not in child_item_ids or aplus_item.status != "succeeded":
                    continue
                version = _version_for_aplus_item(aplus_item)
                if not version or not version.file_path or not Path(version.file_path).exists():
                    continue
                label = _safe_filename(f"{aplus_item.module_name}-{aplus_item.output_mode}", "aplus")
                entries.append(
                    BatchExportEntry(
                        folder=folder,
                        label=f"{output_index:02d}-{label}.png",
                        file_path=version.file_path,
                        version_id=version.id,
                    )
                )
    return entries


def _build_batch_long_image(entries: list[BatchExportEntry], destination: Path, include_watermark: bool) -> Path:
    opened: list[Image.Image] = []
    try:
        for entry in entries:
            image_path = _batch_export_image_path(
                entry.file_path,
                destination,
                f"batch-selection-long-{entry.version_id}",
                include_watermark,
            )
            opened.append(Image.open(image_path).convert("RGB"))
        target_width = max(image.width for image in opened)
        resized: list[Image.Image] = []
        for image in opened:
            if image.width == target_width:
                resized.append(image.copy())
                continue
            target_height = round(image.height * target_width / image.width)
            resized.append(image.resize((target_width, target_height), Image.Resampling.LANCZOS))
        total_height = sum(image.height for image in resized)
        canvas = Image.new("RGB", (target_width, total_height), "white")
        offset = 0
        for image in resized:
            canvas.paste(image, (0, offset))
            offset += image.height
        canvas.save(destination, format="PNG")
        return destination
    finally:
        for image in opened:
            image.close()


def write_batch_selection_export(
    session: Session,
    destination: Path,
    *,
    business_type: str,
    batch_item_ids: list[str],
    child_item_ids: set[str],
    export_format: str = "zip",
    include_watermark: bool = True,
) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    entries = _collect_batch_export_entries(
        session,
        business_type=business_type,
        batch_item_ids=batch_item_ids,
        child_item_ids=child_item_ids,
    )
    if not entries:
        raise ValueError("No selected successful batch results are available for download")
    if export_format == "long_image":
        return _build_batch_long_image(entries, destination, include_watermark)

    used: set[str] = set()
    with ZipFile(destination, "w", ZIP_DEFLATED) as archive:
        for entry in entries:
            export_stem = f"batch-selection-{entry.version_id}"
            image_path = _batch_export_image_path(entry.file_path, destination, export_stem, include_watermark)
            arcname = _unique_arcname(used, f"{entry.folder}/{entry.label}")
            archive.write(image_path, arcname)
    return destination


def write_batch_zip(session: Session, batch: BatchJob, destination: Path, *, include_watermark: bool = True) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    used: set[str] = set()
    with ZipFile(destination, "w", ZIP_DEFLATED) as archive:
        for item in batch.items:
            folder = f"{TASK_DIR_PREFIX}{item.index:02d}"
            if item.name:
                folder += f"-{_safe_filename(item.name, 'product')}"
            if item.generation_job_id:
                job = _load_generation_job(session, item.generation_job_id)
                if not job:
                    continue
                for output_index, generation_item in enumerate(job.items, start=1):
                    if generation_item.status != "succeeded":
                        continue
                    version = _version_for_generation_item(generation_item)
                    if not version or not version.file_path or not Path(version.file_path).exists():
                        continue
                    label = _safe_filename(generation_item.image_type, "image")
                    arcname = _unique_arcname(used, f"{folder}/{output_index:02d}-{label}.png")
                    image_path = _batch_export_image_path(
                        version.file_path,
                        destination,
                        f"batch-{batch.id}-{version.id}",
                        include_watermark,
                    )
                    archive.write(image_path, arcname)
            if item.aplus_generation_job_id:
                job = _load_aplus_job(session, item.aplus_generation_job_id)
                if not job:
                    continue
                for output_index, aplus_item in enumerate(job.items, start=1):
                    if aplus_item.status != "succeeded":
                        continue
                    version = _version_for_aplus_item(aplus_item)
                    if not version or not version.file_path or not Path(version.file_path).exists():
                        continue
                    label = _safe_filename(f"{aplus_item.module_name}-{aplus_item.output_mode}", "aplus")
                    arcname = _unique_arcname(used, f"{folder}/{output_index:02d}-{label}.png")
                    image_path = _batch_export_image_path(
                        version.file_path,
                        destination,
                        f"batch-{batch.id}-{version.id}",
                        include_watermark,
                    )
                    archive.write(image_path, arcname)
    return destination


def _create_fixture_asset(session: Session, settings: Settings, source: Path, original_name: str) -> str:
    if not source.exists():
        raise TaskCreationError(500, f"Validation fixture asset is missing: {source.name}")
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    asset_id = str(uuid4())
    destination = settings.uploads_dir / f"{asset_id}.png"
    shutil.copy2(source, destination)
    with Image.open(destination) as image:
        width, height = image.size
    content = destination.read_bytes()
    asset = Asset(
        id=asset_id,
        original_name=original_name,
        mime_type="image/png",
        file_path=str(destination),
        url=f"/files/uploads/{destination.name}",
        width=width,
        height=height,
        byte_size=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
    )
    session.add(asset)
    session.flush()
    return asset.id


def _fixture_asset_ids(session: Session, settings: Settings, sources: list[Path], prefix: str) -> list[str]:
    return [
        _create_fixture_asset(session, settings, source, f"{prefix}-{index + 1}.png")
        for index, source in enumerate(sources)
    ]


def _suite_fixture_payload(asset_ids: list[str], *, partial: bool) -> BatchJobCreate:
    suffix = "partial" if partial else "success"
    return BatchJobCreate(
        business_type="suite",
        global_params={
            "platform": "Amazon",
            "market": US_MARKET,
            "language": ENGLISH,
            "aspect_ratio": "1:1",
            "count": 7,
            "mode": "smart",
            "model_preference": "fidelity",
            "dry_run": True,
        },
        notification_config={"in_app": True, "completion_toast": False, "validation_fixture": True},
        items=[
            {
                "asset_ids": asset_ids[:2],
                "name": f"Validation suite backpack {suffix}",
                "selling_points": "Lightweight outdoor backpack with organized storage and water-resistant details.",
            },
            {
                "asset_ids": asset_ids[2:4],
                "name": f"Validation suite tumbler {suffix}",
                "selling_points": "Portable insulated tumbler with a non-slip grip and daily commute scenarios.",
            },
        ],
    )


def _aplus_fixture_payload(asset_ids: list[str], *, partial: bool) -> BatchJobCreate:
    suffix = "partial" if partial else "success"
    return BatchJobCreate(
        business_type="aplus",
        global_params={
            "platform": AMAZON,
            "market": US_MARKET,
            "language": ENGLISH,
            "module_selections": [
                {"name": "\u5546\u54c1\u4e3b\u89c6\u89c9", "count": 1},
                {"name": "\u5356\u70b9\u62c6\u89e3", "count": 1},
            ],
            "output_targets": [{"mode": "detail", "aspect_ratio": "1:1"}],
            "dry_run": True,
        },
        notification_config={"in_app": True, "completion_toast": False, "validation_fixture": True},
        items=[
            {
                "asset_ids": asset_ids[:2],
                "name": f"Validation A+ outdoor pack {suffix}",
                "selling_points": "Large capacity, waterproof fabric, organized compartments.",
            },
            {
                "asset_ids": asset_ids[2:4],
                "name": f"Validation A+ commuter pack {suffix}",
                "selling_points": "Lightweight carry, daily commute, detail-focused product modules.",
            },
        ],
    )


def create_validation_fixture_batches(session: Session, business_type: str, settings: Settings) -> list[str]:
    source_assets = APLUS_FIXTURE_ASSETS if business_type == "aplus" else SUITE_FIXTURE_ASSETS
    created_ids: list[str] = []
    for partial in (False, True):
        asset_ids = _fixture_asset_ids(
            session,
            settings,
            source_assets,
            f"validation-{business_type}-{'partial' if partial else 'success'}",
        )
        payload = _aplus_fixture_payload(asset_ids, partial=partial) if business_type == "aplus" else _suite_fixture_payload(asset_ids, partial=partial)
        batch = create_batch_job_record(session, payload, settings)
        created_ids.append(batch.id)
    return created_ids


def mark_validation_fixture_partial_failed(session: Session, batch: BatchJob) -> None:
    target = batch.items[-1] if batch.items else None
    if not target:
        return
    simulated_error = "Validation fixture simulated image failure"
    if target.generation_job_id:
        job = _load_generation_job(session, target.generation_job_id)
        failed_item = job.items[-1] if job and job.items else None
        if job and failed_item:
            failed_item.status = "failed"
            failed_item.error = simulated_error
            job.status = "partial_failed"
            job.error = simulated_error
            job.progress = 100
            job.completed_at = job.completed_at or utcnow()
            target.status = "partial_failed"
            target.error = simulated_error
            target.completed_at = target.completed_at or utcnow()
    elif target.aplus_generation_job_id:
        job = _load_aplus_job(session, target.aplus_generation_job_id)
        failed_item = job.items[-1] if job and job.items else None
        if job and failed_item:
            failed_item.status = "failed"
            failed_item.error = simulated_error
            job.status = "partial_failed"
            job.error = simulated_error
            job.progress = 100
            job.completed_at = job.completed_at or utcnow()
            target.status = "partial_failed"
            target.error = simulated_error
            target.completed_at = target.completed_at or utcnow()
    aggregate_batch_job(session, batch)
