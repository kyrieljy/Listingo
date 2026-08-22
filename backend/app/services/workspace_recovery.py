from __future__ import annotations

from sqlalchemy import ColumnElement, or_, select
from sqlalchemy.orm import Session, selectinload

from backend.app.models import AplusItem, AplusJob, BatchItem, GenerationItem, GenerationJob, VideoItem, VideoJob, utcnow


OPEN_STATUSES = ("queued", "running", "cancelling")
ITEM_OPEN_STATUSES = {"queued", "running", "cancelling"}
INTERRUPTED_ERROR = "Job was interrupted by service restart; retry failed items."
CANCELLED_ERROR = "Job cancellation completed after service restart."
MONITORING_FIXTURE_JOB_ID_PREFIX = "demo-monitor-"
HistoryJobModel = type[GenerationJob] | type[AplusJob] | type[VideoJob]
HistoryItemModel = type[GenerationItem] | type[AplusItem] | type[VideoItem]


def _status_from_item_statuses(statuses: list[str]) -> str:
    if not statuses:
        return "failed"
    if any(status == "cancelled" for status in statuses):
        return "partial_cancelled" if any(status in {"succeeded", "failed"} for status in statuses) else "cancelled"
    if all(status == "succeeded" for status in statuses):
        return "succeeded"
    if any(status == "succeeded" for status in statuses):
        return "partial_failed"
    return "failed"


def _recover_job(job: GenerationJob | AplusJob | VideoJob) -> bool:
    if job.status not in OPEN_STATUSES:
        return False

    target_status = "cancelled" if job.status == "cancelling" else "failed"
    error = CANCELLED_ERROR if target_status == "cancelled" else INTERRUPTED_ERROR
    for item in job.items:
        if item.status in ITEM_OPEN_STATUSES:
            item.status = target_status
            item.error = item.error or error

    statuses = [item.status for item in job.items]
    job.status = _status_from_item_statuses(statuses)
    job.progress = 100
    job.completed_at = utcnow()
    if job.status != "succeeded" and not job.error:
        job.error = error
    return True


def _recover_generation_jobs(session: Session) -> int:
    batch_generation_ids = select(BatchItem.generation_job_id).where(BatchItem.generation_job_id.is_not(None))
    jobs = session.scalars(
        select(GenerationJob)
        .where(
            GenerationJob.status.in_(OPEN_STATUSES),
            GenerationJob.is_admin_test.is_(False),
            ~GenerationJob.id.in_(batch_generation_ids),
        )
        .options(selectinload(GenerationJob.items))
    ).all()
    return sum(1 for job in jobs if _recover_job(job))


def _recover_aplus_plan_jobs(session: Session) -> int:
    batch_plan_ids = select(BatchItem.aplus_plan_job_id).where(BatchItem.aplus_plan_job_id.is_not(None))
    jobs = session.scalars(
        select(AplusJob)
        .where(
            AplusJob.job_type == "plan",
            AplusJob.status.in_(OPEN_STATUSES),
            AplusJob.is_admin_test.is_(False),
            ~AplusJob.id.in_(batch_plan_ids),
        )
        .options(selectinload(AplusJob.items))
    ).all()
    return sum(1 for job in jobs if _recover_job(job))


def _recover_aplus_generation_jobs(session: Session) -> int:
    batch_generation_ids = select(BatchItem.aplus_generation_job_id).where(BatchItem.aplus_generation_job_id.is_not(None))
    jobs = session.scalars(
        select(AplusJob)
        .where(
            AplusJob.job_type == "generation",
            AplusJob.status.in_(OPEN_STATUSES),
            AplusJob.is_admin_test.is_(False),
            ~AplusJob.id.in_(batch_generation_ids),
        )
        .options(selectinload(AplusJob.items))
    ).all()
    return sum(1 for job in jobs if _recover_job(job))


def _recover_video_jobs(session: Session) -> int:
    jobs = session.scalars(
        select(VideoJob)
        .where(VideoJob.status.in_(OPEN_STATUSES), VideoJob.is_admin_test.is_(False))
        .options(selectinload(VideoJob.items))
    ).all()
    return sum(1 for job in jobs if _recover_job(job))


def _repair_empty_monitoring_fixture_jobs(
    session: Session,
    job_model: HistoryJobModel,
    item_model: HistoryItemModel,
    *extra_filters: ColumnElement[bool],
) -> int:
    has_items = select(item_model.id).where(item_model.job_id == job_model.id).exists()
    jobs = session.scalars(
        select(job_model).where(
            job_model.is_admin_test.is_(False),
            ~has_items,
            or_(
                job_model.id.like(f"{MONITORING_FIXTURE_JOB_ID_PREFIX}%"),
                job_model.user_id.like(f"{MONITORING_FIXTURE_JOB_ID_PREFIX}%"),
            ),
            *extra_filters,
        )
    ).all()
    for job in jobs:
        job.is_admin_test = True
    return len(jobs)


def repair_monitoring_fixture_history(session: Session) -> int:
    repaired = (
        _repair_empty_monitoring_fixture_jobs(session, GenerationJob, GenerationItem)
        + _repair_empty_monitoring_fixture_jobs(session, AplusJob, AplusItem, AplusJob.job_type == "plan")
        + _repair_empty_monitoring_fixture_jobs(session, AplusJob, AplusItem, AplusJob.job_type == "generation")
        + _repair_empty_monitoring_fixture_jobs(session, VideoJob, VideoItem)
    )
    if repaired:
        session.commit()
    return repaired


def recover_interrupted_workspace_jobs(session: Session) -> int:
    recovered = (
        _recover_generation_jobs(session)
        + _recover_aplus_plan_jobs(session)
        + _recover_aplus_generation_jobs(session)
        + _recover_video_jobs(session)
    )
    if recovered:
        session.commit()
    return recovered
