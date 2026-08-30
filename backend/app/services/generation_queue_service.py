from __future__ import annotations

"""Unified generation queue scheduling for ordinary jobs and batch items."""

import logging

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from backend.app.config import Settings
from backend.app.core.runtime import RuntimeStateService
from backend.app.core.storage.keys import queue_key
from backend.app.models import BatchItem, BatchJob, GenerationJob, VideoJob, utcnow
from backend.app.security import ApiKeyCipher
from backend.app.services.batch_execution import BatchItemExecutor
from backend.app.services.batch_jobs import invalidate_batch_status
from backend.app.services.generation_queues import GenerationQueueScheduler, NOTIFIED_STATUSES
from backend.app.services.jobs import retry_failed_live_items, run_generation_job
from backend.app.services.notifications import (
    create_batch_result_notification_once,
    create_job_result_notification_once,
)
from backend.app.services.video_jobs import run_video_job


logger = logging.getLogger(__name__)
BATCH_ITEM_TOKEN_PREFIX = "batch_item:"


def batch_item_token(item_id: str) -> str:
    return f"{BATCH_ITEM_TOKEN_PREFIX}{item_id}"


def parse_generation_token(token: str) -> tuple[str, str]:
    if token.startswith(BATCH_ITEM_TOKEN_PREFIX):
        return "batch_item", token[len(BATCH_ITEM_TOKEN_PREFIX) :]
    return "generation", token


class UnifiedGenerationQueueScheduler(GenerationQueueScheduler):
    """Extend the 010 queues with batch-item dispatch while retaining two workers."""

    def __init__(
        self,
        session_factory,
        settings: Settings,
        cipher: ApiKeyCipher,
        *,
        runtime_state: RuntimeStateService,
        poll_interval_seconds: float | None = None,
    ) -> None:
        super().__init__(
            session_factory,
            settings,
            cipher,
            runtime_state=runtime_state,
            poll_interval_seconds=poll_interval_seconds,
        )
        self._batch_executor = BatchItemExecutor(
            session_factory,
            settings,
            cipher,
            runtime_state=runtime_state,
        )

    def enqueue_batch_items(self, item_ids: list[str]) -> None:
        """Append all batch tokens, rolling back partial pushes on storage failure."""
        key = queue_key("generation")
        pushed: list[str] = []
        try:
            for item_id in item_ids:
                token = batch_item_token(item_id)
                self._storage.queue_push(key, token)
                pushed.append(token)
        except Exception:
            for token in pushed:
                try:
                    self._storage.queue_remove(key, token)
                except Exception:
                    logger.warning("Could not remove batch token after enqueue failure: %s", token)
            raise

    def remove_batch_items(self, item_ids: list[str]) -> None:
        key = queue_key("generation")
        for item_id in item_ids:
            self._storage.queue_remove(key, batch_item_token(item_id))

    def rebuild(self) -> dict[str, int]:
        self._batch_executor.recover()
        with self._session_factory() as session:
            batch_generation_ids = select(BatchItem.generation_job_id).where(
                BatchItem.generation_job_id.is_not(None)
            )
            generation_rows = session.execute(
                select(GenerationJob.id, GenerationJob.created_at)
                .where(
                    GenerationJob.status == "queued",
                    GenerationJob.is_admin_test.is_(False),
                    GenerationJob.user_id.is_not(None),
                    ~GenerationJob.id.in_(batch_generation_ids),
                )
                .order_by(GenerationJob.created_at, GenerationJob.id)
            ).all()
            batch_items = session.scalars(
                select(BatchItem)
                .join(BatchJob, BatchJob.id == BatchItem.batch_job_id)
                .where(
                    BatchItem.status == "queued",
                    BatchJob.status.in_(["queued", "running"]),
                )
                .options(selectinload(BatchItem.batch_job))
                .order_by(BatchJob.created_at, BatchItem.index)
            ).all()
            video_ids = self._queued_video_ids(session)

        tasks = [
            (created_at, job_id, job_id)
            for job_id, created_at in generation_rows
        ]
        tasks.extend(
            (
                item.batch_job.created_at,
                f"{item.batch_job.id}:{item.index:06d}",
                batch_item_token(item.id),
            )
            for item in batch_items
        )
        tasks.sort(key=lambda entry: (entry[0], entry[1]))

        generation_key = queue_key("generation")
        self._storage.queue_clear(generation_key)
        for _, _, token in tasks:
            self._storage.queue_push(generation_key, token)

        video_key = queue_key("video")
        self._storage.queue_clear(video_key)
        for job_id in video_ids:
            self._storage.queue_push(video_key, job_id)
        return {"generation": len(tasks), "video": len(video_ids)}

    def _queued_video_ids(self, session) -> list[str]:
        return session.scalars(
            select(VideoJob.id)
            .where(
                VideoJob.status == "queued",
                VideoJob.is_admin_test.is_(False),
                VideoJob.user_id.is_not(None),
            )
            .order_by(VideoJob.created_at, VideoJob.id)
        ).all()

    def _reconcile_job_notifications(self) -> int:
        created = 0
        with self._session_factory() as session:
            batch_generation_ids = select(BatchItem.generation_job_id).where(
                BatchItem.generation_job_id.is_not(None)
            )
            generation_jobs = session.scalars(
                select(GenerationJob).where(
                    GenerationJob.status.in_(NOTIFIED_STATUSES),
                    GenerationJob.is_admin_test.is_(False),
                    GenerationJob.user_id.is_not(None),
                    ~GenerationJob.id.in_(batch_generation_ids),
                )
            ).all()
            video_jobs = session.scalars(
                select(VideoJob).where(
                    VideoJob.status.in_(NOTIFIED_STATUSES),
                    VideoJob.is_admin_test.is_(False),
                    VideoJob.user_id.is_not(None),
                )
            ).all()
            for kind, jobs in (("generation", generation_jobs), ("video", video_jobs)):
                for job in jobs:
                    before_count = len(session.new)
                    create_job_result_notification_once(
                        session,
                        job.user_id,
                        category=kind,
                        job_id=job.id,
                        status=job.status,
                        dry_run=job.dry_run,
                    )
                    if len(session.new) > before_count:
                        created += 1
            session.commit()
        return created

    def reconcile_notifications(self) -> int:
        try:
            created = self._reconcile_job_notifications()
        except Exception:
            logger.warning("Generation queue notification compensation failed", exc_info=True)
            created = 0
        try:
            with self._session_factory() as session:
                batches = session.scalars(
                    select(BatchJob).where(
                        BatchJob.status.in_(NOTIFIED_STATUSES),
                        BatchJob.user_id.is_not(None),
                    )
                ).all()
                for batch in batches:
                    before_count = len(session.new)
                    create_batch_result_notification_once(
                        session,
                        batch.user_id,
                        batch_id=batch.id,
                        business_type=batch.business_type,
                        status=batch.status,
                        completed_count=batch.completed_count,
                        failed_count=batch.failed_count,
                        total_count=batch.total_count,
                    )
                    if len(session.new) > before_count:
                        created += 1
                session.commit()
        except Exception:
            logger.warning("Batch queue notification compensation failed", exc_info=True)
        return created

    async def tick(self, kind: str) -> bool:
        if kind != "generation":
            return await super().tick(kind)

        token = self._storage.queue_pop(queue_key("generation"))
        if token is None:
            return False
        task_kind, task_id = parse_generation_token(token)
        if task_kind == "batch_item":
            if self._claim_batch_item(task_id):
                await self._batch_executor.execute(task_id)
                self._notify_batch_terminal(task_id)
            return True

        retry_generation = False
        with self._session_factory() as session:
            job = session.scalar(select(GenerationJob).where(GenerationJob.id == task_id).with_for_update())
            if not job or job.status != "queued":
                session.commit()
                return True
            retry_generation = any(item.status == "failed" for item in job.items)
            job.status = "running"
            job.started_at = job.started_at or utcnow()
            job.completed_at = None
            job.error = None
            session.commit()

        try:
            if retry_generation:
                await retry_failed_live_items(task_id, self._session_factory, self._settings, self._cipher)
            else:
                await run_generation_job(task_id, self._session_factory, self._settings, self._cipher)
        except Exception as exc:
            logger.exception("Queued generation job generation %s failed", task_id)
            self._mark_claim_failed("generation", task_id, str(exc))

        self._notify_terminal("generation", task_id)
        self._schedule_external_notification(category="generation", job_id=task_id)
        return True

    def _claim_batch_item(self, item_id: str) -> bool:
        with self._session_factory() as session:
            item = session.scalar(
                select(BatchItem)
                .where(BatchItem.id == item_id)
                .options(selectinload(BatchItem.batch_job))
                .with_for_update()
            )
            if (
                not item
                or item.status != "queued"
                or not item.batch_job
                or item.batch_job.status not in {"queued", "running"}
            ):
                session.commit()
                return False
            item.status = "running"
            item.started_at = item.started_at or utcnow()
            item.completed_at = None
            item.error = None
            item.batch_job.status = "running"
            item.batch_job.started_at = item.batch_job.started_at or utcnow()
            session.commit()
            invalidate_batch_status(item.batch_job_id, self._runtime_state)
            return True

    def _notify_batch_terminal(self, item_id: str) -> None:
        try:
            with self._session_factory() as session:
                item = session.get(BatchItem, item_id)
                batch = session.get(BatchJob, item.batch_job_id) if item else None
                if not batch or not batch.user_id or batch.status not in NOTIFIED_STATUSES:
                    return
                create_batch_result_notification_once(
                    session,
                    batch.user_id,
                    batch_id=batch.id,
                    business_type=batch.business_type,
                    status=batch.status,
                    completed_count=batch.completed_count,
                    failed_count=batch.failed_count,
                    total_count=batch.total_count,
                )
                session.commit()
                self._schedule_external_notification(
                    category="batch", job_id=batch.id, business_type=batch.business_type
                )
        except Exception:
            logger.warning("Queued batch terminal notification failed: %s", item_id, exc_info=True)
