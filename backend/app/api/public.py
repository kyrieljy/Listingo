from __future__ import annotations

from collections.abc import Sequence
import json
from pathlib import Path
from typing import Any
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse
from PIL import Image
from sqlalchemy import ColumnElement, Select, or_, select
from sqlalchemy.orm import Session, selectinload

from backend.app.database import get_session
from backend.app.core.rate_limit import RateLimitResult, rate_limit_headers
from backend.app.models import (
    Asset,
    AplusItem,
    AplusJob,
    AplusVersion,
    BatchItem,
    BatchJob,
    ExecutionLog,
    GenerationItem,
    GenerationJob,
    GenerationVersion,
    Prompt,
    PromptVersion,
    VideoItem,
    VideoJob,
    VideoVersion,
    Workflow,
    User,
    utcnow,
)
from backend.app.schemas import (
    AssetOut,
    AnalyticsEventCreate,
    AplusGenerationJobCreate,
    AplusJobOut,
    AplusPlanJobCreate,
    AplusVersionOut,
    BatchJobCreate,
    BatchJobOut,
    BatchValidationFixturesCreate,
    CopywritingAssistCreate,
    CopywritingAssistOut,
    GenerationJobCreate,
    GenerationJobOut,
    GenerationVersionCreate,
    GenerationVersionOut,
    ImageTextOcrOut,
    ImageTextVersionCreate,
    VideoCopywritingAssistCreate,
    VideoCopywritingAssistOut,
    VideoJobCreate,
    VideoJobOut,
    VideoVersionOut,
    WorkspaceConfigOut,
)
from backend.app.services.analytics import analytics_event_dict, record_analytics_event
from backend.app.services.aplus_jobs import (
    cancel_aplus_job,
    create_aplus_generation_job_from_plan,
    create_dryrun_aplus_child_version,
    create_live_aplus_child_version,
    load_aplus_job,
    retry_aplus_item,
    retry_failed_aplus_items,
    run_aplus_generation_job,
    run_aplus_plan_job,
    serialize_aplus_job,
)
from backend.app.services.jobs import (
    _call_llm_with_fallback,
    _enabled_provider,
    cancel_generation_job,
    JOB_FINAL_STATUSES,
    create_dryrun_child_version,
    create_live_child_version,
    image_provider_route,
    retry_failed_live_items,
    retry_live_item,
    run_generation_job,
)
from backend.app.services.job_creation import (
    TaskCreationError,
    create_aplus_generation_job_record,
    create_aplus_plan_job_record,
    create_generation_job_record,
)
from backend.app.services.image_text_edit import (
    create_dryrun_aplus_text_version,
    create_dryrun_generation_text_version,
    create_live_aplus_text_version,
    create_live_generation_text_version,
    detect_text_lines_with_status,
)
from backend.app.services.batch_jobs import (
    cancel_batch_job,
    cached_batch_job_payload,
    create_batch_job_record,
    create_validation_fixture_batches,
    invalidate_batch_status,
    load_batch_job,
    mark_validation_fixture_partial_failed,
    retry_failed_batch_job,
    serialize_batch_job,
    write_batch_selection_export,
    write_batch_zip,
)
from backend.app.services.metrics import increment_analytics_event_counters
from backend.app.services.content_safety import (
    ContentSafetyBlocked,
    ensure_content_safe,
    run_content_safety_review,
    run_local_text_safety_review,
)
from backend.app.services.providers import ProviderClient
from backend.app.services.provider_routing import route_provider_codes
from backend.app.services.redaction import safe_json
from backend.app.services.storage import store_upload
from backend.app.services.video_jobs import (
    build_video_copywriting_user_prompt,
    cancel_video_job,
    FINAL_STATUSES,
    create_dryrun_video_child_version,
    create_live_video_child_version,
    dryrun_video_script,
    public_asset_url,
    run_video_job,
)
from backend.app.services.watermarking import apply_ai_watermark
from backend.app.services.auth import ensure_owner_access, get_current_user, get_optional_user
from backend.app.services.subscriptions import confirm_quota, release_quota, reserve_quota
from backend.app.core.storage.base import StorageUnavailableError


def _fail_closed_compensate(session_factory, job_id: str, model, ref_type: str) -> None:
    """Redis 入队失败时回滚已落库的 queued 任务并释放预留额度（fail-closed）。

    队列是正确性依赖：入队失败不应留下会稍后自动执行的 queued 任务，
    因此将任务置为 cancelled 并释放本次预留额度，用户看到的是明确的失败。
    """
    with session_factory() as session:
        job = session.get(model, job_id)
        if job and job.status == "queued":
            release_quota(session, ref_type=ref_type, ref_id=job.id)
            job.status = "cancelled"
            job.completed_at = utcnow()
            for item in job.items:
                if item.status == "queued":
                    item.status = "cancelled"
            session.commit()


router = APIRouter(prefix="/api/v1", tags=["generation"])

GENERATION_RATE_LIMIT = 20
GENERATION_RATE_WINDOW_SECONDS = 60
GENERATION_RATE_LIMIT_KEY = "workspace:generation"


def _consume_generation_rate_limit(request: Request, response: Response) -> RateLimitResult:
    result = request.app.state.rate_limiter.consume_rate_limit(
        GENERATION_RATE_LIMIT_KEY,
        GENERATION_RATE_LIMIT,
        GENERATION_RATE_WINDOW_SECONDS,
    )
    for name, value in rate_limit_headers(result).items():
        response.headers[name] = value
    if not result.allowed:
        raise HTTPException(
            status_code=429,
            detail="生成请求过于频繁，请稍后再试",
            headers=rate_limit_headers(result),
        )
    return result


def raise_task_creation_error(exc: TaskCreationError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


PAID_EXPORT_PLANS = {"standard", "advanced", "enterprise", "internal"}
MONITORING_FIXTURE_JOB_ID_PREFIX = "demo-monitor-"


def enforce_watermark_access(current_user: User, include_watermark: bool) -> None:
    if include_watermark or current_user.current_plan_code in PAID_EXPORT_PLANS or current_user.role == "admin":
        return
    raise HTTPException(status_code=403, detail="当前套餐不支持无水印下载，请升级订阅")


def asset_query_for_user(asset_ids: list[str], current_user: User) -> Select[tuple[Asset]]:
    query = select(Asset).where(Asset.id.in_(asset_ids))
    if current_user.role != "admin":
        query = query.where(or_(Asset.user_id == current_user.id, Asset.user_id.is_(None)))
    return query


def ensure_job_owner(current_user: User, job: GenerationJob | VideoJob | AplusJob | BatchJob) -> None:
    ensure_owner_access(current_user, job.user_id)


def visible_history_job_filters(
    job_model: type[GenerationJob] | type[VideoJob] | type[AplusJob],
) -> tuple[ColumnElement[bool], ColumnElement[bool]]:
    return (
        ~job_model.id.like(f"{MONITORING_FIXTURE_JOB_ID_PREFIX}%"),
        or_(job_model.user_id.is_(None), ~job_model.user_id.like(f"{MONITORING_FIXTURE_JOB_ID_PREFIX}%")),
    )


def reserve_edit_quota(session: Session, current_user: User, *, description: str = "") -> str | None:
    quota_ref = str(uuid4())
    reserve_quota(
        session,
        current_user,
        action_key="edit_generation",
        amount=1,
        ref_type="edit_generation",
        ref_id=quota_ref,
        description=description,
    )
    return quota_ref


def confirm_edit_quota(session: Session, quota_ref: str | None) -> None:
    if quota_ref:
        confirm_quota(session, ref_type="edit_generation", ref_id=quota_ref)


def release_edit_quota(session: Session, quota_ref: str | None) -> None:
    if quota_ref:
        release_quota(session, ref_type="edit_generation", ref_id=quota_ref)


@router.get("/workspace-config", response_model=WorkspaceConfigOut)
def get_workspace_config(request: Request) -> dict[str, Any]:
    settings = request.app.state.settings
    return {
        "max_upload_bytes": settings.max_upload_bytes,
        "max_batch_tasks": settings.max_batch_tasks,
        "max_batch_item_assets": settings.max_batch_item_assets,
        "max_active_batch_items": settings.max_active_batch_items,
        "max_provider_concurrency": settings.max_provider_concurrency,
    }


@router.post("/analytics/events", status_code=201)
def create_analytics_event(
    payload: AnalyticsEventCreate,
    request: Request,
    current_user: User | None = Depends(get_optional_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    event = record_analytics_event(
        session,
        request,
        payload,
        user_id=current_user.id if current_user else None,
    )
    session.commit()
    increment_analytics_event_counters(event, getattr(request.app.state, "runtime_state", None))
    return {"ok": True, "event": analytics_event_dict(event)}


def serialize_version(version: GenerationVersion) -> dict:
    return {
        "id": version.id,
        "parent_version_id": version.parent_version_id,
        "version_no": version.version_no,
        "instruction": version.instruction,
        "url": version.url,
        "created_at": version.created_at,
    }


def serialize_job(job: GenerationJob) -> dict:
    serialized_items = []
    for item in job.items:
        serialized_items.append(
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
                "versions": [serialize_version(version) for version in item.versions],
            }
        )
    return {
        "id": job.id,
        "status": job.status,
        "dry_run": job.dry_run,
        "progress": job.progress,
        "count": job.count,
        "params": json.loads(job.params_json),
        "error": job.error,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "completed_at": job.completed_at,
        "items": serialized_items,
    }


def serialize_video_version(version: VideoVersion) -> dict:
    return {
        "id": version.id,
        "parent_version_id": version.parent_version_id,
        "version_no": version.version_no,
        "instruction": version.instruction,
        "url": version.url,
        "remote_url": version.remote_url,
        "created_at": version.created_at,
    }


def serialize_video_job(job: VideoJob) -> dict:
    return {
        "id": job.id,
        "status": job.status,
        "dry_run": job.dry_run,
        "progress": job.progress,
        "count": job.count,
        "params": json.loads(job.params_json),
        "error": job.error,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "completed_at": job.completed_at,
        "items": [
            {
                "id": item.id,
                "index": item.index,
                "video_type": item.video_type,
                "status": item.status,
                "provider_id": item.provider_id,
                "provider_task_id": item.provider_task_id,
                "error": item.error,
                "prompt_text": item.prompt_text,
                "script_markdown": item.script_markdown,
                "current_version_id": item.current_version_id,
                "versions": [serialize_video_version(version) for version in item.versions],
            }
            for item in job.items
        ],
    }


def load_job(session: Session, job_id: str) -> GenerationJob:
    job = session.scalar(
        select(GenerationJob)
        .where(GenerationJob.id == job_id)
        .options(selectinload(GenerationJob.items).selectinload(GenerationItem.versions))
    )
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    return job


def load_video_job(session: Session, job_id: str) -> VideoJob:
    job = session.scalar(
        select(VideoJob)
        .where(VideoJob.id == job_id)
        .options(selectinload(VideoJob.items).selectinload(VideoItem.versions))
    )
    if not job:
        raise HTTPException(status_code=404, detail="视频任务不存在")
    return job


def load_aplus_job_or_404(session: Session, job_id: str) -> AplusJob:
    job = load_aplus_job(session, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="A+ 任务不存在")
    return job


def dryrun_copywriting_text(source: str) -> str:
    product_name = source.replace("，", ",").split(",")[0].strip() or "商品"
    return f"""---
### 1. 商品定位
- 品名：{product_name}
### 2. 适用场景
- 日常通勤：上班族随身携带，路上与办公室都方便取用。
- 桌面使用：家庭用户放在桌面，喝水、饮茶时顺手稳定。
- 短途出行：外出人群放入背包或车内，满足临时饮用需求。
### 3. 5大核心卖点
1. 简洁外观：日常搭配自然不突兀。
2. 防滑握持：拿取更稳，降低滑落风险。
3. 场景百搭：通勤、居家与出行都适用。
4. 使用顺手：高频饮用场景取放更方便。
5. 视觉干净：适合电商主图与场景图表达。
---"""


def parse_copywriting_text(raw: str) -> str:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict) and isinstance(parsed.get("selling_points"), str):
        return parsed["selling_points"].strip()
    return raw.strip()


def build_long_image(image_paths: list[str], destination: Path) -> None:
    opened: list[Image.Image] = []
    try:
        for image_path in image_paths:
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
    finally:
        for image in opened:
            image.close()


def export_image_path(image_path: str, exports_dir: Path, export_stem: str, include_watermark: bool) -> str:
    if not include_watermark:
        return image_path
    destination = exports_dir / "watermarked" / f"{export_stem}.png"
    return str(apply_ai_watermark(image_path, destination))


def build_copywriting_user_prompt(payload: CopywritingAssistCreate) -> str:
    input_mode = "image_with_text" if payload.selling_points.strip() else "image_only"
    return json.dumps(
        {
            "input_mode": input_mode,
            "platform": payload.platform,
            "market": payload.market,
            "image_text_language": payload.language,
            "output_language": "简体中文",
            "selling_points": payload.selling_points,
            "instruction": (
                "必须使用简体中文输出 AI 帮写候选内容；"
                "image_text_language 只代表后续图片画面文案语言，不得影响本节点输出语言。"
            ),
        },
        ensure_ascii=False,
    )


@router.post("/assets", response_model=AssetOut, status_code=201)
async def create_asset(
    request: Request,
    file: UploadFile,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    asset = await store_upload(file, request.app.state.settings)
    asset.user_id = current_user.id
    session.add(asset)
    session.commit()
    session.refresh(asset)
    return asset


@router.post("/batch-jobs", response_model=BatchJobOut, status_code=201)
async def create_batch_job(
    payload: BatchJobCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    settings = request.app.state.settings
    try:
        batch = create_batch_job_record(session, payload, settings, user_id=current_user.id)
        reserve_quota(
            session,
            current_user,
            action_key="batch_suite" if payload.business_type == "suite" else "batch_aplus",
            amount=len(payload.items),
            ref_type="batch_job",
            ref_id=batch.id,
            description="batch task",
        )
    except TaskCreationError as exc:
        session.rollback()
        raise_task_creation_error(exc)
    except HTTPException:
        session.rollback()
        raise
    session.commit()
    invalidate_batch_status(batch.id, getattr(request.app.state, "runtime_state", None))
    batch = load_batch_job(session, batch.id)
    if not settings.testing and hasattr(request.app.state, "batch_scheduler"):
        await request.app.state.batch_scheduler.tick(wait=False)
    return serialize_batch_job(session, batch)


@router.get("/batch-jobs", response_model=list[BatchJobOut])
def list_batch_jobs(current_user: User = Depends(get_current_user), session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    query = (
        select(BatchJob)
        .where(*visible_history_job_filters(BatchJob))
        .options(selectinload(BatchJob.items))
        .order_by(BatchJob.created_at.desc())
    )
    if current_user.role != "admin":
        query = query.where(BatchJob.user_id == current_user.id)
    jobs = session.scalars(query).all()
    return [serialize_batch_job(session, job, include_children=False) for job in jobs]


@router.post("/batch-jobs/validation-fixtures", response_model=list[BatchJobOut], status_code=201)
async def create_batch_validation_fixtures_endpoint(
    payload: BatchValidationFixturesCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only administrators can create validation fixtures")
    settings = request.app.state.settings
    try:
        batch_ids = create_validation_fixture_batches(session, payload.business_type, settings)
    except TaskCreationError as exc:
        session.rollback()
        raise_task_creation_error(exc)
    session.commit()
    for batch_id in batch_ids:
        invalidate_batch_status(batch_id, getattr(request.app.state, "runtime_state", None))

    if hasattr(request.app.state, "batch_scheduler"):
        await request.app.state.batch_scheduler.tick(wait=True)

    session.expire_all()
    if len(batch_ids) > 1:
        partial = load_batch_job(session, batch_ids[1])
        if partial:
            mark_validation_fixture_partial_failed(session, partial)
            session.commit()
            invalidate_batch_status(partial.id, getattr(request.app.state, "runtime_state", None))
            session.expire_all()

    jobs = [load_batch_job(session, batch_id) for batch_id in batch_ids]
    return [serialize_batch_job(session, job) for job in jobs if job]


@router.get("/batch-jobs/selection-download")
def download_batch_selection_results(
    request: Request,
    business_type: str = Query(pattern="^(suite|aplus)$"),
    batch_item_ids: str = Query(min_length=1),
    item_ids: str = Query(min_length=1),
    format: str = Query(default="zip", pattern="^(zip|long_image)$"),
    include_watermark: bool = Query(default=True),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> FileResponse:
    enforce_watermark_access(current_user, include_watermark)
    selected_batch_item_ids = [item_id for item_id in batch_item_ids.split(",") if item_id]
    selected_child_item_ids = {item_id for item_id in item_ids.split(",") if item_id}
    owners = session.scalars(
        select(BatchJob.user_id)
        .join(BatchItem, BatchItem.batch_job_id == BatchJob.id)
        .where(BatchItem.id.in_(selected_batch_item_ids))
    ).all()
    if current_user.role != "admin" and any(owner_id != current_user.id for owner_id in owners):
        raise HTTPException(status_code=404, detail="Batch item does not exist")
    suffix = "png" if format == "long_image" else "zip"
    destination = request.app.state.settings.exports_dir / f"batch-selection-{business_type}.{suffix}"
    try:
        exported = write_batch_selection_export(
            session,
            destination,
            business_type=business_type,
            batch_item_ids=selected_batch_item_ids,
            child_item_ids=selected_child_item_ids,
            export_format=format,
            include_watermark=include_watermark,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if format == "long_image":
        return FileResponse(exported, media_type="image/png", filename=f"batch-selection-{business_type}.png")
    return FileResponse(exported, media_type="application/zip", filename=f"batch-selection-{business_type}.zip")


@router.get("/batch-jobs/{batch_id}", response_model=BatchJobOut)
def get_batch_job(
    batch_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    batch = load_batch_job(session, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch job does not exist")
    ensure_job_owner(current_user, batch)
    return cached_batch_job_payload(session, batch, runtime=getattr(request.app.state, "runtime_state", None))


@router.post("/batch-jobs/{batch_id}/cancel", response_model=BatchJobOut)
def cancel_batch_job_endpoint(
    batch_id: str,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    batch = load_batch_job(session, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch job does not exist")
    ensure_job_owner(current_user, batch)
    return serialize_batch_job(session, cancel_batch_job(session, batch))


@router.post("/batch-jobs/{batch_id}/retry-failed", response_model=BatchJobOut)
async def retry_failed_batch_job_endpoint(
    batch_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    batch = load_batch_job(session, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch job does not exist")
    ensure_job_owner(current_user, batch)
    failed_count = sum(1 for item in batch.items if item.status in {"failed", "partial_failed"})
    if failed_count:
        reserve_quota(
            session,
            current_user,
            action_key="batch_suite" if batch.business_type == "suite" else "batch_aplus",
            amount=failed_count,
            ref_type="batch_job",
            ref_id=batch.id,
            description="retry batch task",
        )
    retry_failed_batch_job(session, batch)
    batch = load_batch_job(session, batch_id)
    if not request.app.state.settings.testing and hasattr(request.app.state, "batch_scheduler"):
        await request.app.state.batch_scheduler.tick(wait=False)
    return serialize_batch_job(session, batch)


@router.get("/batch-jobs/{batch_id}/download")
def download_batch_results(
    batch_id: str,
    request: Request,
    include_watermark: bool = Query(default=True),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> FileResponse:
    enforce_watermark_access(current_user, include_watermark)
    batch = load_batch_job(session, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch job does not exist")
    ensure_job_owner(current_user, batch)
    destination = request.app.state.settings.exports_dir / f"batch-{batch.id}.zip"
    write_batch_zip(session, batch, destination, include_watermark=include_watermark)
    return FileResponse(destination, media_type="application/zip", filename=f"batch-{batch.id}.zip")


@router.post("/generation-jobs", response_model=GenerationJobOut, status_code=201)
async def create_generation_job(
    payload: GenerationJobCreate,
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _consume_generation_rate_limit(request, response)
    if len(payload.asset_ids) > 6:
        raise HTTPException(status_code=422, detail="Single generation jobs allow at most 6 product images")
    try:
        job = create_generation_job_record(session, payload, max_asset_count=6, user_id=current_user.id)
        reserve_quota(
            session,
            current_user,
            action_key="image_generation",
            amount=payload.count,
            ref_type="generation_job",
            ref_id=job.id,
            description="product suite generation",
        )
    except TaskCreationError as exc:
        session.rollback()
        raise_task_creation_error(exc)
    except HTTPException:
        session.rollback()
        raise
    session.commit()
    session.refresh(job)
    scheduler = request.app.state.generation_queue_scheduler
    try:
        scheduler.enqueue("generation", job.id)
    except StorageUnavailableError:
        _fail_closed_compensate(request.app.state.session_factory, job.id, GenerationJob, "generation_job")
        raise HTTPException(status_code=503, detail="后台队列暂不可用，请稍后重试")
    return serialize_job(job)

    assets = session.scalars(select(Asset).where(Asset.id.in_(payload.asset_ids))).all()
    if len(assets) != len(payload.asset_ids):
        raise HTTPException(status_code=422, detail="存在无效商品图")
    if not payload.dry_run:
        try:
            _enabled_provider(session, "llm", "default")
            _enabled_provider(session, "llm", "fallback")
            image_provider_route(payload.model_preference, session)
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    prompt = session.scalar(select(Prompt).where(Prompt.code == "ecommerce-meta"))
    workflow = session.scalar(select(Workflow).where(Workflow.code == "product-suite-v1"))
    if not prompt or not prompt.active_version_id or not workflow or not workflow.active_version_id:
        raise HTTPException(status_code=500, detail="核心 Prompt 或 Workflow 未启用")
    auxiliary_codes = ("product-vision", "copywriting-assist", "edit-rewrite", "image-text-edit", "content-safety-review")
    auxiliary_prompts = session.scalars(select(Prompt).where(Prompt.code.in_(auxiliary_codes))).all()
    prompt_versions = {
        item.code: item.active_version_id for item in auxiliary_prompts if item.active_version_id
    }
    if len(prompt_versions) != len(auxiliary_codes):
        raise HTTPException(status_code=500, detail="Prompt 工程辅助资产未完整启用")
    params = payload.model_dump()
    params["_prompt_versions"] = prompt_versions
    input_text = json.dumps(payload.model_dump(exclude={"asset_ids", "dry_run"}), ensure_ascii=False)
    try:
        ensure_content_safe(run_local_text_safety_review(input_text), "输入内容安全拦截")
    except ContentSafetyBlocked as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    job = GenerationJob(
        status="queued",
        dry_run=payload.dry_run,
        params_json=json.dumps(params, ensure_ascii=False),
        asset_ids_json=json.dumps(payload.asset_ids),
        count=payload.count,
        progress=0,
        prompt_version_id=prompt.active_version_id,
        workflow_version_id=workflow.active_version_id,
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    background_tasks.add_task(
        run_generation_job,
        job.id,
        request.app.state.session_factory,
        request.app.state.settings,
        request.app.state.cipher,
    )
    return serialize_job(job)


@router.post("/copywriting-assist", response_model=CopywritingAssistOut)
async def assist_copywriting(
    payload: CopywritingAssistCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    user_prompt = build_copywriting_user_prompt(payload)
    try:
        ensure_content_safe(run_local_text_safety_review(user_prompt), "输入内容安全拦截")
    except ContentSafetyBlocked as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if payload.dry_run:
        source = payload.selling_points.strip() or "突出产品用途、材质体验与使用场景"
        result = dryrun_copywriting_text(source)
        session.add(
            ExecutionLog(
                node="copywriting_assist",
                status="succeeded",
                request_summary=safe_json(payload.model_dump()),
                response_summary=safe_json({"selling_points": result}),
                dry_run=True,
            )
        )
        session.commit()
        return CopywritingAssistOut(selling_points=result, dry_run=True)

    prompt = session.scalar(select(Prompt).where(Prompt.code == "copywriting-assist"))
    prompt_version = session.get(PromptVersion, prompt.active_version_id) if prompt and prompt.active_version_id else None
    if not prompt_version:
        raise HTTPException(status_code=500, detail="AI 帮写 Prompt 未启用")
    safety_prompt = session.scalar(select(Prompt).where(Prompt.code == "content-safety-review"))
    safety_version = session.get(PromptVersion, safety_prompt.active_version_id) if safety_prompt and safety_prompt.active_version_id else None
    if not safety_version:
        raise HTTPException(status_code=500, detail="内容安全审计 Prompt 未启用")
    assets = session.scalars(asset_query_for_user(payload.asset_ids, current_user)).all() if payload.asset_ids else []
    if len(assets) != len(payload.asset_ids):
        raise HTTPException(status_code=422, detail="AI 帮写包含无效商品图")
    image_paths = [asset.file_path for asset in assets]
    llm_default = _enabled_provider(session, "llm", "default")
    llm_fallback = _enabled_provider(session, "llm", "fallback")
    try:
        input_review, input_provider = await run_content_safety_review(
            ProviderClient(),
            llm_default,
            llm_fallback,
            request.app.state.cipher,
            safety_version,
            subject="copywriting_input",
            text=user_prompt,
            image_paths=image_paths,
        )
        ensure_content_safe(input_review, "输入内容安全拦截")
    except ContentSafetyBlocked as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"输入内容安全拦截：安全审计失败：{exc}") from exc
    session.add(
        ExecutionLog(
            node="content_safety",
            provider_id=input_provider.id,
            status="succeeded",
            request_summary=safe_json({"subject": "copywriting_input", "asset_count": len(image_paths)}),
            response_summary=safe_json(input_review.model_dump()),
            dry_run=False,
        )
    )
    session.commit()
    raw, provider = await _call_llm_with_fallback(
        ProviderClient(),
        llm_default,
        llm_fallback,
        request.app.state.cipher,
        prompt_version.content,
        user_prompt,
        image_paths=image_paths,
        response_format=None,
    )
    selling_points = parse_copywriting_text(raw)
    if not selling_points:
        raise HTTPException(status_code=502, detail="AI 帮写返回空内容")
    try:
        output_review, output_provider = await run_content_safety_review(
            ProviderClient(),
            llm_default,
            llm_fallback,
            request.app.state.cipher,
            safety_version,
            subject="copywriting_output",
            text=selling_points,
        )
        ensure_content_safe(output_review, "内容安全拦截")
    except ContentSafetyBlocked as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"内容安全拦截：安全审计失败：{exc}") from exc
    session.add(
        ExecutionLog(
            node="content_safety",
            provider_id=output_provider.id,
            status="succeeded",
            request_summary=safe_json({"subject": "copywriting_output"}),
            response_summary=safe_json(output_review.model_dump()),
            dry_run=False,
        )
    )
    session.add(
        ExecutionLog(
            node="copywriting_assist",
            provider_id=provider.id,
            status="succeeded",
            request_summary=safe_json({**payload.model_dump(exclude={"dry_run", "asset_ids"}), "asset_count": len(image_paths), "prompt_version_id": prompt_version.id}),
            response_summary=safe_json({"selling_points": selling_points}),
            dry_run=False,
        )
    )
    session.commit()
    return CopywritingAssistOut(
        selling_points=selling_points.strip(),
        dry_run=False,
        provider_code=provider.code,
    )


@router.post("/aplus-plan-jobs", response_model=AplusJobOut, status_code=201)
async def create_aplus_plan_job(
    payload: AplusPlanJobCreate,
    background_tasks: BackgroundTasks,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    if len(payload.asset_ids) > 6:
        raise HTTPException(status_code=422, detail="Single A+ plan jobs allow at most 6 product images")
    try:
        job = create_aplus_plan_job_record(session, payload, max_asset_count=6, user_id=current_user.id)
    except TaskCreationError as exc:
        session.rollback()
        raise_task_creation_error(exc)
    session.commit()
    session.refresh(job)
    background_tasks.add_task(run_aplus_plan_job, job.id, request.app.state.session_factory, request.app.state.cipher)
    return serialize_aplus_job(load_aplus_job_or_404(session, job.id))

    assets = session.scalars(select(Asset).where(Asset.id.in_(payload.asset_ids))).all()
    if len(assets) != len(payload.asset_ids):
        raise HTTPException(status_code=422, detail="存在无效商品图")
    input_text = json.dumps(payload.model_dump(exclude={"asset_ids", "dry_run"}), ensure_ascii=False)
    try:
        ensure_content_safe(run_local_text_safety_review(input_text), "输入内容安全拦截")
    except ContentSafetyBlocked as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not payload.dry_run:
        try:
            _enabled_provider(session, "llm", "default")
            _enabled_provider(session, "llm", "fallback")
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    prompt = session.scalar(select(Prompt).where(Prompt.code == "aplus-meta"))
    prompt_version = session.get(PromptVersion, prompt.active_version_id) if prompt and prompt.active_version_id else None
    product_vision = session.scalar(select(Prompt).where(Prompt.code == "product-vision"))
    product_vision_version = (
        session.get(PromptVersion, product_vision.active_version_id)
        if product_vision and product_vision.active_version_id
        else None
    )
    if not prompt_version or not product_vision_version:
        raise HTTPException(status_code=500, detail="A+ Prompt 工程资产未完整启用")
    params = payload.model_dump()
    params["module_total"] = payload.module_total
    params["_prompt_versions"] = {"product-vision": product_vision_version.id}
    job = AplusJob(
        job_type="plan",
        status="queued",
        dry_run=payload.dry_run,
        params_json=json.dumps(params, ensure_ascii=False),
        asset_ids_json=json.dumps(payload.asset_ids),
        count=payload.module_total,
        progress=0,
        prompt_version_id=prompt_version.id,
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    background_tasks.add_task(run_aplus_plan_job, job.id, request.app.state.session_factory, request.app.state.cipher)
    return serialize_aplus_job(load_aplus_job_or_404(session, job.id))


@router.get("/aplus-plan-jobs/{job_id}", response_model=AplusJobOut)
def get_aplus_plan_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    job = load_aplus_job_or_404(session, job_id)
    ensure_job_owner(current_user, job)
    if job.job_type != "plan":
        raise HTTPException(status_code=404, detail="A+ 方案任务不存在")
    return serialize_aplus_job(job)


@router.post("/aplus-plan-jobs/{job_id}/cancel", response_model=AplusJobOut)
def cancel_aplus_plan_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    job = load_aplus_job_or_404(session, job_id)
    ensure_job_owner(current_user, job)
    if job.job_type != "plan":
        raise HTTPException(status_code=404, detail="A+ 方案任务不存在")
    return serialize_aplus_job(cancel_aplus_job(session, job))


@router.get("/aplus-plan-jobs", response_model=list[AplusJobOut])
def list_aplus_plan_jobs(current_user: User = Depends(get_current_user), session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    batch_plan_ids = select(BatchItem.aplus_plan_job_id).where(BatchItem.aplus_plan_job_id.is_not(None))
    query = (
        select(AplusJob)
        .where(
            AplusJob.job_type == "plan",
            AplusJob.is_admin_test.is_(False),
            ~AplusJob.id.in_(batch_plan_ids),
            *visible_history_job_filters(AplusJob),
        )
        .options(selectinload(AplusJob.items).selectinload(AplusItem.versions))
        .order_by(AplusJob.created_at.desc())
    )
    if current_user.role != "admin":
        query = query.where(AplusJob.user_id == current_user.id)
    jobs = session.scalars(query).all()
    return [serialize_aplus_job(job) for job in jobs]


@router.post("/aplus-generation-jobs", response_model=AplusJobOut, status_code=201)
async def create_aplus_generation_job(
    payload: AplusGenerationJobCreate,
    background_tasks: BackgroundTasks,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    try:
        job = create_aplus_generation_job_record(session, payload, user_id=current_user.id)
        reserve_quota(
            session,
            current_user,
            action_key="aplus_generation",
            amount=job.count,
            ref_type="aplus_job",
            ref_id=job.id,
            description="A+ generation",
        )
    except TaskCreationError as exc:
        session.rollback()
        raise_task_creation_error(exc)
    except HTTPException:
        session.rollback()
        raise
    session.commit()
    session.refresh(job)
    background_tasks.add_task(
        run_aplus_generation_job,
        job.id,
        request.app.state.session_factory,
        request.app.state.settings,
        request.app.state.cipher,
    )
    return serialize_aplus_job(load_aplus_job_or_404(session, job.id))

    plan_job = load_aplus_job_or_404(session, payload.plan_job_id)
    if plan_job.job_type != "plan" or plan_job.status != "succeeded":
        raise HTTPException(status_code=409, detail="A+ 方案尚未生成成功")
    plan_params = json.loads(plan_job.params_json)
    if any(target.mode != "detail" for target in payload.output_targets) and plan_params.get("platform") != "亚马逊":
        raise HTTPException(status_code=422, detail="普通 A+ 和高级 A+ 只支持亚马逊平台")
    if not payload.dry_run:
        route_keys = {
            "aplus_mobile" if target.mode == "amazon_aplus_advanced_mobile" else "aplus_detail"
            for target in payload.output_targets
        }
        try:
            for route_key in route_keys:
                route_provider_codes(session, route_key)
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    prompt = session.scalar(select(Prompt).where(Prompt.code == "aplus-meta"))
    if not prompt or not prompt.active_version_id:
        raise HTTPException(status_code=500, detail="A+ Meta Prompt 未启用")
    job = create_aplus_generation_job_from_plan(session, plan_job, payload, prompt.active_version_id)
    session.commit()
    session.refresh(job)
    background_tasks.add_task(
        run_aplus_generation_job,
        job.id,
        request.app.state.session_factory,
        request.app.state.settings,
        request.app.state.cipher,
    )
    return serialize_aplus_job(load_aplus_job_or_404(session, job.id))


@router.get("/aplus-generation-jobs", response_model=list[AplusJobOut])
def list_aplus_generation_jobs(current_user: User = Depends(get_current_user), session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    batch_generation_ids = select(BatchItem.aplus_generation_job_id).where(BatchItem.aplus_generation_job_id.is_not(None))
    query = (
        select(AplusJob)
        .where(
            AplusJob.job_type == "generation",
            AplusJob.is_admin_test.is_(False),
            ~AplusJob.id.in_(batch_generation_ids),
            *visible_history_job_filters(AplusJob),
        )
        .options(selectinload(AplusJob.items).selectinload(AplusItem.versions))
        .order_by(AplusJob.created_at.desc())
    )
    if current_user.role != "admin":
        query = query.where(AplusJob.user_id == current_user.id)
    jobs = session.scalars(query).all()
    return [serialize_aplus_job(job) for job in jobs]


@router.get("/aplus-generation-jobs/{job_id}", response_model=AplusJobOut)
def get_aplus_generation_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    job = load_aplus_job_or_404(session, job_id)
    ensure_job_owner(current_user, job)
    if job.job_type != "generation":
        raise HTTPException(status_code=404, detail="A+ 生成任务不存在")
    return serialize_aplus_job(job)


@router.post("/aplus-generation-jobs/{job_id}/cancel", response_model=AplusJobOut)
def cancel_aplus_generation_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    job = load_aplus_job_or_404(session, job_id)
    ensure_job_owner(current_user, job)
    if job.job_type != "generation":
        raise HTTPException(status_code=404, detail="A+ 生成任务不存在")
    return serialize_aplus_job(cancel_aplus_job(session, job))


@router.post("/aplus-generation-jobs/{job_id}/retry-failed", response_model=AplusJobOut)
async def retry_failed_aplus_generation_job(
    job_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    job = load_aplus_job_or_404(session, job_id)
    ensure_job_owner(current_user, job)
    if job.job_type != "generation":
        raise HTTPException(status_code=404, detail="A+ 生成任务不存在")
    if not any(item.status == "failed" for item in job.items):
        return serialize_aplus_job(job)
    reserve_quota(
        session,
        current_user,
        action_key="aplus_generation",
        amount=sum(1 for item in job.items if item.status == "failed"),
        ref_type="aplus_job",
        ref_id=job.id,
        description="retry A+ generation",
    )
    session.commit()
    await retry_failed_aplus_items(
        job.id,
        request.app.state.session_factory,
        request.app.state.settings,
        request.app.state.cipher,
    )
    return serialize_aplus_job(load_aplus_job_or_404(session, job.id))


@router.post("/aplus-items/{item_id}/retry", response_model=AplusJobOut)
async def retry_single_aplus_item(
    item_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    item = session.get(AplusItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="A+ item not found")
    job = load_aplus_job_or_404(session, item.job_id)
    ensure_job_owner(current_user, job)
    if job.job_type != "generation":
        raise HTTPException(status_code=404, detail="A+ 生成任务不存在")
    if item.status == "failed":
        reserve_quota(
            session,
            current_user,
            action_key="aplus_generation",
            amount=1,
            ref_type="aplus_job",
            ref_id=job.id,
            description="retry A+ item",
        )
        session.commit()
        retried_job_id = await retry_aplus_item(
            item.id,
            request.app.state.session_factory,
            request.app.state.settings,
            request.app.state.cipher,
        )
        if retried_job_id:
            session.expire_all()
            job = load_aplus_job_or_404(session, retried_job_id)
    return serialize_aplus_job(job)


@router.get("/aplus-generation-jobs/{job_id}/download")
def download_aplus_results(
    job_id: str,
    request: Request,
    item_ids: str = Query(min_length=1),
    format: str = Query(default="zip", pattern="^(zip|long_image)$"),
    include_watermark: bool = Query(default=True),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> FileResponse:
    enforce_watermark_access(current_user, include_watermark)
    job = load_aplus_job_or_404(session, job_id)
    ensure_job_owner(current_user, job)
    selected = {item_id for item_id in item_ids.split(",") if item_id}
    versions: list[tuple[AplusItem, AplusVersion]] = []
    for item in job.items:
        if item.id not in selected or not item.current_version_id:
            continue
        current = next((version for version in item.versions if version.id == item.current_version_id), None)
        if current and Path(current.file_path).exists():
            versions.append((item, current))
    if not versions:
        raise HTTPException(status_code=422, detail="没有可下载的 A+ 结果")
    if format == "long_image":
        export_path = request.app.state.settings.exports_dir / f"listingo-aplus-{job.id}-long.png"
        build_long_image([
            export_image_path(
                version.file_path,
                request.app.state.settings.exports_dir,
                f"aplus-{job.id}-{version.id}-long-source",
                include_watermark,
            )
            for _, version in versions
        ], export_path)
        return FileResponse(export_path, media_type="image/png", filename=f"listingo-aplus-{job.id}-long.png")

    archive = request.app.state.settings.exports_dir / f"listingo-aplus-{job.id}.zip"
    with ZipFile(archive, "w", ZIP_DEFLATED) as zip_file:
        for item, version in versions:
            image_path = export_image_path(
                version.file_path,
                request.app.state.settings.exports_dir,
                f"aplus-{job.id}-{version.id}",
                include_watermark,
            )
            zip_file.write(image_path, arcname=f"{item.index + 1:02d}-{item.module_name}-{item.aspect_ratio}.png")
    return FileResponse(archive, media_type="application/zip", filename=f"listingo-aplus-{job.id}.zip")


def _current_version(
    versions: Sequence[GenerationVersion | AplusVersion],
    current_version_id: str | None,
) -> GenerationVersion | AplusVersion | None:
    if current_version_id:
        current = next((version for version in versions if version.id == current_version_id), None)
        if current:
            return current
    return versions[-1] if versions else None


def _ocr_language_hint(job: GenerationJob | AplusJob | None) -> str | None:
    if not job:
        return None
    try:
        params = json.loads(job.params_json or "{}")
    except ValueError:
        return None
    plan_params = params.get("plan_params") if isinstance(params.get("plan_params"), dict) else {}
    language = params.get("language") or plan_params.get("language")
    return str(language) if language else None


@router.post("/aplus-items/{item_id}/text-ocr", response_model=ImageTextOcrOut)
def ocr_aplus_item_text(
    item_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    item = session.scalar(
        select(AplusItem).where(AplusItem.id == item_id).options(selectinload(AplusItem.versions), selectinload(AplusItem.job))
    )
    if not item:
        raise HTTPException(status_code=404, detail="A+ item not found")
    ensure_job_owner(current_user, item.job)
    current = _current_version(item.versions, item.current_version_id)
    if not current or not current.file_path or not Path(current.file_path).exists():
        raise HTTPException(status_code=422, detail="Current A+ image version is unavailable for OCR")
    result = detect_text_lines_with_status(
        current.file_path,
        settings=request.app.state.settings,
        language_hint=_ocr_language_hint(item.job),
    )
    return ImageTextOcrOut(lines=result.lines, warning=result.warning)


@router.post("/aplus-items/{item_id}/text-versions", response_model=AplusVersionOut, status_code=201)
async def create_aplus_text_version(
    item_id: str,
    payload: ImageTextVersionCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    item = session.scalar(
        select(AplusItem).where(AplusItem.id == item_id).options(selectinload(AplusItem.versions))
    )
    if not item:
        raise HTTPException(status_code=404, detail="A+ item not found")
    job = session.get(AplusJob, item.job_id)
    if not job:
        raise HTTPException(status_code=404, detail="A+ job not found")
    ensure_job_owner(current_user, job)
    quota_ref = reserve_edit_quota(session, current_user, description="A+ text edit")
    try:
        if job.dry_run:
            version = create_dryrun_aplus_text_version(session, item, payload.lines, request.app.state.settings)
        else:
            version = await create_live_aplus_text_version(
                session, item, payload.lines, request.app.state.settings, request.app.state.cipher
            )
        confirm_edit_quota(session, quota_ref)
        session.commit()
        return version
    except ValueError as exc:
        release_edit_quota(session, quota_ref)
        session.commit()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ContentSafetyBlocked as exc:
        release_edit_quota(session, quota_ref)
        session.commit()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        release_edit_quota(session, quota_ref)
        session.commit()
        if str(exc).startswith("鍐呭瀹夊叏鎷︽埅") or str(exc).startswith("Input content safety blocked"):
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/aplus-items/{item_id}/versions", response_model=AplusVersionOut, status_code=201)
async def create_aplus_version(
    item_id: str,
    payload: GenerationVersionCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    item = session.scalar(
        select(AplusItem).where(AplusItem.id == item_id).options(selectinload(AplusItem.versions))
    )
    if not item:
        raise HTTPException(status_code=404, detail="A+ 生成项不存在")
    job = session.get(AplusJob, item.job_id)
    if not job:
        raise HTTPException(status_code=404, detail="A+ 任务不存在")
    ensure_job_owner(current_user, job)
    instruction = payload.instruction.strip()
    if len(instruction) < 2:
        raise HTTPException(status_code=422, detail="Instruction must be at least 2 characters")
    quota_ref = reserve_edit_quota(session, current_user, description="A+ image edit")
    if job.dry_run:
        version = create_dryrun_aplus_child_version(session, item, instruction, request.app.state.settings)
        confirm_edit_quota(session, quota_ref)
        session.commit()
        return version
    try:
        version = await create_live_aplus_child_version(
            session, item, instruction, request.app.state.settings, request.app.state.cipher
        )
        confirm_edit_quota(session, quota_ref)
        session.commit()
        return version
    except RuntimeError as exc:
        release_edit_quota(session, quota_ref)
        session.commit()
        if str(exc).startswith("内容安全拦截"):
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        raise


@router.post("/video-copywriting-assist", response_model=VideoCopywritingAssistOut)
async def assist_video_copywriting(
    payload: VideoCopywritingAssistCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    user_prompt = build_video_copywriting_user_prompt(payload)
    try:
        ensure_content_safe(run_local_text_safety_review(user_prompt), "输入内容安全拦截")
    except ContentSafetyBlocked as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if payload.dry_run:
        text = payload.selling_points.strip() or "请突出商品核心痛点、适用人群、使用场景和 15 秒视频转化目标。"
        result = (
            f"1. 核心卖点：{text}\n"
            f"2. 视频方向：{', '.join(payload.video_types or ['UGC 种草'])}\n"
            "3. 建议结构：前三秒抓痛点，中段展示商品解决过程，最后定格产品和简单行动号召。"
        )
        session.add(
            ExecutionLog(
                node="video_copywriting_assist",
                status="succeeded",
                request_summary=safe_json(payload.model_dump()),
                response_summary=safe_json({"selling_points": result}),
                dry_run=True,
            )
        )
        session.commit()
        return VideoCopywritingAssistOut(selling_points=result, dry_run=True)

    prompt = session.scalar(select(Prompt).where(Prompt.code == "copywriting-assist"))
    prompt_version = session.get(PromptVersion, prompt.active_version_id) if prompt and prompt.active_version_id else None
    safety_prompt = session.scalar(select(Prompt).where(Prompt.code == "content-safety-review"))
    safety_version = session.get(PromptVersion, safety_prompt.active_version_id) if safety_prompt and safety_prompt.active_version_id else None
    if not prompt_version or not safety_version:
        raise HTTPException(status_code=500, detail="视频帮写依赖 Prompt 未启用")
    assets = session.scalars(asset_query_for_user(payload.asset_ids, current_user)).all() if payload.asset_ids else []
    if len(assets) != len(payload.asset_ids):
        raise HTTPException(status_code=422, detail="视频帮写包含无效商品图")
    image_paths = [asset.file_path for asset in assets]
    llm_default = _enabled_provider(session, "llm", "default")
    llm_fallback = _enabled_provider(session, "llm", "fallback")
    try:
        input_review, input_provider = await run_content_safety_review(
            ProviderClient(),
            llm_default,
            llm_fallback,
            request.app.state.cipher,
            safety_version,
            subject="video_copywriting_input",
            text=user_prompt,
            image_paths=image_paths,
        )
        ensure_content_safe(input_review, "输入内容安全拦截")
    except ContentSafetyBlocked as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"输入内容安全拦截：安全审计失败：{exc}") from exc
    raw, provider = await _call_llm_with_fallback(
        ProviderClient(),
        llm_default,
        llm_fallback,
        request.app.state.cipher,
        prompt_version.content,
        user_prompt,
        image_paths=image_paths,
        response_format=None,
    )
    selling_points = parse_copywriting_text(raw)
    try:
        output_review, output_provider = await run_content_safety_review(
            ProviderClient(),
            llm_default,
            llm_fallback,
            request.app.state.cipher,
            safety_version,
            subject="video_copywriting_output",
            text=selling_points,
        )
        ensure_content_safe(output_review, "内容安全拦截")
    except ContentSafetyBlocked as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"内容安全拦截：安全审计失败：{exc}") from exc
    session.add_all(
        [
            ExecutionLog(
                node="content_safety",
                provider_id=input_provider.id,
                status="succeeded",
                request_summary=safe_json({"subject": "video_copywriting_input", "asset_count": len(image_paths)}),
                response_summary=safe_json(input_review.model_dump()),
                dry_run=False,
            ),
            ExecutionLog(
                node="content_safety",
                provider_id=output_provider.id,
                status="succeeded",
                request_summary=safe_json({"subject": "video_copywriting_output"}),
                response_summary=safe_json(output_review.model_dump()),
                dry_run=False,
            ),
            ExecutionLog(
                node="video_copywriting_assist",
                provider_id=provider.id,
                status="succeeded",
                request_summary=safe_json(payload.model_dump(exclude={"asset_ids"})),
                response_summary=safe_json({"selling_points": selling_points}),
                dry_run=False,
            ),
        ]
    )
    session.commit()
    return VideoCopywritingAssistOut(selling_points=selling_points, dry_run=False, provider_code=provider.code)


@router.post("/video-jobs", response_model=VideoJobOut, status_code=201)
async def create_video_job(
    payload: VideoJobCreate,
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _consume_generation_rate_limit(request, response)
    assets = session.scalars(asset_query_for_user(payload.asset_ids, current_user)).all()
    if len(assets) != len(payload.asset_ids):
        raise HTTPException(status_code=422, detail="存在无效商品图")
    prompt = session.scalar(select(Prompt).where(Prompt.code == "ecommerce-video-meta-15s"))
    prompt_version = session.get(PromptVersion, prompt.active_version_id) if prompt and prompt.active_version_id else None
    if not prompt_version:
        raise HTTPException(status_code=500, detail="视频 Meta Prompt 未启用")
    params = payload.model_dump()
    input_text = json.dumps(payload.model_dump(exclude={"asset_ids", "dry_run"}), ensure_ascii=False)
    try:
        ensure_content_safe(run_local_text_safety_review(input_text), "输入内容安全拦截")
    except ContentSafetyBlocked as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if not payload.dry_run:
        try:
            _enabled_provider(session, "llm", "default")
            _enabled_provider(session, "llm", "fallback")
            _enabled_provider(session, "video", "default")
            for asset in assets:
                public_asset_url(request.app.state.settings, asset)
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    params["_prompt_versions"] = {"ecommerce-video-meta-15s": prompt_version.id}
    job = VideoJob(
        user_id=current_user.id,
        status="queued",
        dry_run=payload.dry_run,
        params_json=json.dumps(params, ensure_ascii=False),
        asset_ids_json=json.dumps(payload.asset_ids),
        count=len(payload.video_types),
        progress=0,
        prompt_version_id=prompt_version.id,
    )
    session.add(job)
    session.flush()
    for index, video_type in enumerate(payload.video_types):
        session.add(
            VideoItem(
                job_id=job.id,
                index=index,
                video_type=video_type,
                status="queued",
            )
        )
    reserve_quota(
        session,
        current_user,
        action_key="video_generation",
        amount=len(payload.video_types),
        ref_type="video_job",
        ref_id=job.id,
        description="video generation",
    )
    session.commit()
    session.refresh(job)
    scheduler = request.app.state.generation_queue_scheduler
    try:
        scheduler.enqueue("video", job.id)
    except StorageUnavailableError:
        _fail_closed_compensate(request.app.state.session_factory, job.id, VideoJob, "video_job")
        raise HTTPException(status_code=503, detail="后台队列暂不可用，请稍后重试")
    return serialize_video_job(load_video_job(session, job.id))


@router.get("/video-jobs", response_model=list[VideoJobOut])
def list_video_jobs(current_user: User = Depends(get_current_user), session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    query = (
        select(VideoJob)
        .where(VideoJob.is_admin_test.is_(False), *visible_history_job_filters(VideoJob))
        .options(selectinload(VideoJob.items).selectinload(VideoItem.versions))
        .order_by(VideoJob.created_at.desc())
    )
    if current_user.role != "admin":
        query = query.where(VideoJob.user_id == current_user.id)
    jobs = session.scalars(query).all()
    return [serialize_video_job(job) for job in jobs]


@router.get("/video-jobs/{job_id}", response_model=VideoJobOut)
def get_video_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    job = load_video_job(session, job_id)
    ensure_job_owner(current_user, job)
    return serialize_video_job(job)


@router.post("/video-jobs/{job_id}/cancel", response_model=VideoJobOut)
def cancel_video_generation_job(
    job_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    job = load_video_job(session, job_id)
    ensure_job_owner(current_user, job)
    scheduler = request.app.state.generation_queue_scheduler
    # 重新加锁读取最新状态，确保与 worker 认领的并发安全
    fresh = session.execute(select(VideoJob).where(VideoJob.id == job_id).with_for_update()).scalar_one_or_none()
    if fresh is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    if fresh.status == "running":
        raise HTTPException(status_code=409, detail="任务正在生成中，无法取消")
    if fresh.status in FINAL_STATUSES:
        return serialize_video_job(fresh)
    scheduler.remove("video", job_id)
    return serialize_video_job(cancel_video_job(session, fresh))


@router.post("/video-jobs/{job_id}/retry-failed", response_model=VideoJobOut)
async def retry_failed_video_job(
    job_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    job = load_video_job(session, job_id)
    ensure_job_owner(current_user, job)
    if not any(item.status == "failed" for item in job.items):
        return serialize_video_job(job)
    reserve_quota(
        session,
        current_user,
        action_key="video_generation",
        amount=sum(1 for item in job.items if item.status == "failed"),
        ref_type="video_job",
        ref_id=job.id,
        description="retry video generation",
    )
    for item in job.items:
        if item.status == "failed":
            item.status = "queued"
            item.error = None
    job.status = "queued"
    job.progress = 0
    session.commit()
    scheduler = request.app.state.generation_queue_scheduler
    try:
        scheduler.enqueue("video", job.id)
    except StorageUnavailableError:
        _fail_closed_compensate(request.app.state.session_factory, job.id, VideoJob, "video_job")
        raise HTTPException(status_code=503, detail="后台队列暂不可用，请稍后重试")
    return serialize_video_job(load_video_job(session, job.id))


@router.get("/video-jobs/{job_id}/download")
def download_video_results(
    job_id: str,
    request: Request,
    item_ids: str = Query(min_length=1),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> FileResponse:
    job = load_video_job(session, job_id)
    enforce_watermark_access(current_user, include_watermark=True)
    ensure_job_owner(current_user, job)
    selected = {item_id for item_id in item_ids.split(",") if item_id}
    versions: list[tuple[VideoItem, VideoVersion]] = []
    for item in job.items:
        if item.id not in selected or not item.current_version_id:
            continue
        current = next((version for version in item.versions if version.id == item.current_version_id), None)
        if current and current.file_path and Path(current.file_path).exists():
            versions.append((item, current))
    if not versions:
        raise HTTPException(status_code=422, detail="没有可下载的视频结果")
    if len(versions) == 1:
        item, version = versions[0]
        return FileResponse(version.file_path, media_type="video/mp4", filename=f"listingo-video-{item.index + 1:02d}.mp4")
    archive = request.app.state.settings.exports_dir / f"listingo-video-{job.id}.zip"
    with ZipFile(archive, "w", ZIP_DEFLATED) as zip_file:
        for item, version in versions:
            zip_file.write(version.file_path, arcname=f"{item.index + 1:02d}-{item.video_type}.mp4")
    return FileResponse(archive, media_type="application/zip", filename=f"listingo-video-{job.id}.zip")


@router.post("/video-items/{item_id}/versions", response_model=VideoVersionOut, status_code=201)
async def create_video_version(
    item_id: str,
    payload: GenerationVersionCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    item = session.scalar(
        select(VideoItem).where(VideoItem.id == item_id).options(selectinload(VideoItem.versions))
    )
    if not item:
        raise HTTPException(status_code=404, detail="Video item not found")
    job = session.get(VideoJob, item.job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Video job not found")
    ensure_job_owner(current_user, job)
    instruction = payload.instruction.strip()
    if len(instruction) < 2:
        raise HTTPException(status_code=422, detail="Instruction must be at least 2 characters")
    quota_ref = reserve_edit_quota(session, current_user, description="video edit")
    try:
        if job.dry_run:
            version = create_dryrun_video_child_version(session, item, instruction)
        else:
            version = await create_live_video_child_version(
            session,
            item,
            instruction,
            request.app.state.settings,
            request.app.state.cipher,
            request.app.state.session_factory,
            )
        confirm_edit_quota(session, quota_ref)
        session.commit()
        return version
    except ValueError as exc:
        release_edit_quota(session, quota_ref)
        session.commit()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ContentSafetyBlocked as exc:
        release_edit_quota(session, quota_ref)
        session.commit()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        release_edit_quota(session, quota_ref)
        session.commit()
        if str(exc).startswith("Input content safety blocked"):
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        raise


@router.get("/generation-jobs", response_model=list[GenerationJobOut])
def list_generation_jobs(current_user: User = Depends(get_current_user), session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    batch_generation_ids = select(BatchItem.generation_job_id).where(BatchItem.generation_job_id.is_not(None))
    query = (
        select(GenerationJob)
        .where(
            GenerationJob.is_admin_test.is_(False),
            ~GenerationJob.id.in_(batch_generation_ids),
            *visible_history_job_filters(GenerationJob),
        )
        .options(selectinload(GenerationJob.items).selectinload(GenerationItem.versions))
        .order_by(GenerationJob.created_at.desc())
    )
    if current_user.role != "admin":
        query = query.where(GenerationJob.user_id == current_user.id)
    jobs = session.scalars(query).all()
    return [serialize_job(job) for job in jobs]


@router.get("/generation-jobs/{job_id}", response_model=GenerationJobOut)
def get_generation_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    job = load_job(session, job_id)
    ensure_job_owner(current_user, job)
    return serialize_job(job)


@router.post("/generation-jobs/{job_id}/cancel", response_model=GenerationJobOut)
def cancel_generation_job_endpoint(
    job_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    job = load_job(session, job_id)
    ensure_job_owner(current_user, job)
    scheduler = request.app.state.generation_queue_scheduler
    # 重新加锁读取最新状态，确保与 worker 认领的并发安全
    fresh = session.execute(select(GenerationJob).where(GenerationJob.id == job_id).with_for_update()).scalar_one_or_none()
    if fresh is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    if fresh.status == "running":
        raise HTTPException(status_code=409, detail="任务正在生成中，无法取消")
    if fresh.status in JOB_FINAL_STATUSES:
        return serialize_job(fresh)
    scheduler.remove("generation", job_id)
    return serialize_job(cancel_generation_job(session, fresh))


@router.post("/generation-jobs/{job_id}/retry-failed", response_model=GenerationJobOut)
async def retry_failed(
    job_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    job = load_job(session, job_id)
    ensure_job_owner(current_user, job)
    failed = [item for item in job.items if item.status == "failed"]
    if not failed:
        return serialize_job(job)
    if job.dry_run:
        raise HTTPException(status_code=409, detail="Dryrun 不会产生可重试的模型失败项")
    reserve_quota(
        session,
        current_user,
        action_key="image_generation",
        amount=len(failed),
        ref_type="generation_job",
        ref_id=job.id,
        description="retry image generation",
    )
    # Re-queue the job but deliberately keep the failed items in `failed`: the worker
    # detects failed items on claim and routes to `retry_failed_live_items`, which
    # redoes only those. Resetting them here would make the worker regenerate the
    # whole job instead. The worker drops any job that is not `queued` on claim.
    job.status = "queued"
    job.progress = 0
    job.error = None
    job.completed_at = None
    session.commit()
    scheduler = request.app.state.generation_queue_scheduler
    try:
        scheduler.enqueue("generation", job.id)
    except StorageUnavailableError:
        _fail_closed_compensate(request.app.state.session_factory, job.id, GenerationJob, "generation_job")
        raise HTTPException(status_code=503, detail="后台队列暂不可用，请稍后重试")
    return serialize_job(load_job(session, job.id))


@router.post("/generation-items/{item_id}/retry", response_model=GenerationJobOut)
async def retry_single_generation_item(
    item_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    item = session.get(GenerationItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="生成图片不存在")
    job = load_job(session, item.job_id)
    ensure_job_owner(current_user, job)
    if item.status == "failed":
        reserve_quota(
            session,
            current_user,
            action_key="image_generation",
            amount=1,
            ref_type="generation_job",
            ref_id=job.id,
            description="retry image item",
        )
        session.commit()
        retried_job_id = await retry_live_item(
            item.id,
            request.app.state.session_factory,
            request.app.state.settings,
            request.app.state.cipher,
        )
        if retried_job_id:
            session.expire_all()
            job = load_job(session, retried_job_id)
    return serialize_job(job)


@router.get("/generation-jobs/{job_id}/download")
def download_results(
    job_id: str,
    request: Request,
    item_ids: str = Query(min_length=1),
    format: str = Query(default="zip", pattern="^(zip|long_image)$"),
    include_watermark: bool = Query(default=True),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> FileResponse:
    enforce_watermark_access(current_user, include_watermark)
    job = load_job(session, job_id)
    ensure_job_owner(current_user, job)
    selected = {item_id for item_id in item_ids.split(",") if item_id}
    versions: list[tuple[GenerationItem, GenerationVersion]] = []
    for item in job.items:
        if item.id not in selected or not item.current_version_id:
            continue
        current = next((version for version in item.versions if version.id == item.current_version_id), None)
        if current and Path(current.file_path).exists():
            versions.append((item, current))
    if not versions:
        raise HTTPException(status_code=422, detail="没有可下载的已选结果")

    if format == "long_image":
        export_path = request.app.state.settings.exports_dir / f"listingo-{job.id}-long.png"
        build_long_image([
            export_image_path(
                version.file_path,
                request.app.state.settings.exports_dir,
                f"{job.id}-{version.id}-long-source",
                include_watermark,
            )
            for _, version in versions
        ], export_path)
        return FileResponse(export_path, media_type="image/png", filename=f"listingo-{job.id}-long.png")

    archive = request.app.state.settings.exports_dir / f"listingo-{job.id}.zip"
    with ZipFile(archive, "w", ZIP_DEFLATED) as zip_file:
        for item, version in versions:
            image_path = export_image_path(
                version.file_path,
                request.app.state.settings.exports_dir,
                f"{job.id}-{version.id}",
                include_watermark,
            )
            zip_file.write(image_path, arcname=f"{item.index + 1:02d}-{item.image_type}.png")
    return FileResponse(archive, media_type="application/zip", filename=f"listingo-{job.id}.zip")


@router.post("/generation-items/{item_id}/text-ocr", response_model=ImageTextOcrOut)
def ocr_generation_item_text(
    item_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    item = session.scalar(
        select(GenerationItem)
        .where(GenerationItem.id == item_id)
        .options(selectinload(GenerationItem.versions), selectinload(GenerationItem.job))
    )
    if not item:
        raise HTTPException(status_code=404, detail="Generation item not found")
    ensure_job_owner(current_user, item.job)
    current = _current_version(item.versions, item.current_version_id)
    if not current or not current.file_path or not Path(current.file_path).exists():
        raise HTTPException(status_code=422, detail="Current generated image version is unavailable for OCR")
    result = detect_text_lines_with_status(
        current.file_path,
        settings=request.app.state.settings,
        language_hint=_ocr_language_hint(item.job),
    )
    return ImageTextOcrOut(lines=result.lines, warning=result.warning)


@router.post("/generation-items/{item_id}/text-versions", response_model=GenerationVersionOut, status_code=201)
async def create_generation_text_version(
    item_id: str,
    payload: ImageTextVersionCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    item = session.scalar(
        select(GenerationItem).where(GenerationItem.id == item_id).options(selectinload(GenerationItem.versions))
    )
    if not item:
        raise HTTPException(status_code=404, detail="Generation item not found")
    job = session.get(GenerationJob, item.job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Generation job not found")
    ensure_job_owner(current_user, job)
    quota_ref = reserve_edit_quota(session, current_user, description="image text edit")
    try:
        if job.dry_run:
            version = create_dryrun_generation_text_version(session, item, payload.lines, request.app.state.settings)
        else:
            params = json.loads(job.params_json)
            version = await create_live_generation_text_version(
                session,
                item,
                str(params.get("aspect_ratio") or "1:1"),
                payload.lines,
                request.app.state.settings,
                request.app.state.cipher,
            )
        confirm_edit_quota(session, quota_ref)
        session.commit()
        return version
    except ValueError as exc:
        release_edit_quota(session, quota_ref)
        session.commit()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ContentSafetyBlocked as exc:
        release_edit_quota(session, quota_ref)
        session.commit()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        if str(exc).startswith("鍐呭瀹夊叏鎷︽埅") or str(exc).startswith("Input content safety blocked"):
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/generation-items/{item_id}/versions", response_model=GenerationVersionOut, status_code=201)
async def create_generation_version(
    item_id: str,
    payload: GenerationVersionCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    item = session.scalar(
        select(GenerationItem).where(GenerationItem.id == item_id).options(selectinload(GenerationItem.versions))
    )
    if not item:
        raise HTTPException(status_code=404, detail="生成项不存在")
    job = session.get(GenerationJob, item.job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    ensure_job_owner(current_user, job)
    instruction = payload.instruction.strip()
    if instruction and len(instruction) < 2:
        raise HTTPException(status_code=422, detail="Instruction must be at least 2 characters")
    quota_ref = reserve_edit_quota(session, current_user, description="image edit")
    if job.dry_run:
        version = create_dryrun_child_version(session, item, instruction, request.app.state.settings)
        confirm_edit_quota(session, quota_ref)
        session.commit()
        return version
    try:
        version = await create_live_child_version(
            session, item, instruction, request.app.state.settings, request.app.state.cipher
        )
        confirm_edit_quota(session, quota_ref)
        session.commit()
        return version
    except ContentSafetyBlocked as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        if str(exc).startswith("内容安全拦截"):
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        raise
