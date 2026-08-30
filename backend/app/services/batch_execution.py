from __future__ import annotations

"""Execution helpers for batch items consumed by the generation queue worker."""

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker, selectinload

from backend.app.config import Settings
from backend.app.core.runtime import RuntimeStateService
from backend.app.models import AplusJob, BatchItem, BatchJob, GenerationItem, GenerationJob, utcnow
from backend.app.security import ApiKeyCipher
from backend.app.services.aplus_jobs import (
    run_aplus_generation_job,
    run_aplus_plan_job,
    retry_failed_aplus_items,
)
from backend.app.services.batch_jobs import (
    FAILED_STATUSES,
    FINAL_STATUSES,
    aggregate_batch_job,
    create_aplus_generation_for_batch_item,
    invalidate_batch_status,
    sync_batch_item_from_children,
)
from backend.app.services.jobs import retry_failed_live_items, run_generation_job


logger = logging.getLogger(__name__)


class BatchItemExecutor:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        settings: Settings,
        cipher: ApiKeyCipher,
        *,
        runtime_state: RuntimeStateService | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._cipher = cipher
        self._runtime_state = runtime_state

    def recover(self) -> None:
        """Return interrupted batch items to the queue-rebuildable state."""
        with self._session_factory() as session:
            batches = session.scalars(
                select(BatchJob)
                .where(BatchJob.status.in_(["queued", "running", "cancelling"]))
                .options(selectinload(BatchJob.items))
            ).all()
            for batch in batches:
                if batch.status == "running":
                    batch.status = "queued"
                for item in batch.items:
                    if item.status == "running":
                        sync_batch_item_from_children(session, item)
                        if item.status == "running":
                            item.status = "queued"
                aggregate_batch_job(session, batch)
            session.commit()
            for batch in batches:
                invalidate_batch_status(batch.id, self._runtime_state)

    async def execute(self, item_id: str) -> None:
        """Execute one already-claimed batch item and aggregate its parent batch."""
        try:
            with self._session_factory() as session:
                item = session.get(BatchItem, item_id)
                if not item:
                    return
                batch = session.get(BatchJob, item.batch_job_id)
                if not batch or batch.status in FINAL_STATUSES:
                    return
                business_type = batch.business_type
                generation_job_id = item.generation_job_id
                aplus_plan_job_id = item.aplus_plan_job_id
                aplus_generation_job_id = item.aplus_generation_job_id

            if business_type == "suite":
                await self._run_suite_item(generation_job_id)
            else:
                aplus_generation_job_id = await self._run_aplus_item(
                    item_id,
                    aplus_plan_job_id,
                    aplus_generation_job_id,
                )

            with self._session_factory() as session:
                item = session.get(BatchItem, item_id)
                if not item:
                    return
                if aplus_generation_job_id:
                    item.aplus_generation_job_id = aplus_generation_job_id
                sync_batch_item_from_children(session, item)
                if item.status == "running":
                    item.status = "succeeded"
                    item.completed_at = utcnow()
                batch = session.scalar(
                    select(BatchJob)
                    .where(BatchJob.id == item.batch_job_id)
                    .options(selectinload(BatchJob.items))
                )
                if batch:
                    aggregate_batch_job(session, batch)
                session.commit()
                invalidate_batch_status(batch.id if batch else item.batch_job_id, self._runtime_state)
        except Exception as exc:
            logger.exception("Queued batch item %s failed", item_id)
            self._mark_failed(item_id, str(exc))

    def _mark_failed(self, item_id: str, error: str) -> None:
        with self._session_factory() as session:
            item = session.get(BatchItem, item_id)
            if not item:
                return
            if item.status not in {"queued", "running"}:
                return
            item.status = "failed"
            item.error = error
            item.completed_at = utcnow()
            batch = session.scalar(
                select(BatchJob)
                .where(BatchJob.id == item.batch_job_id)
                .options(selectinload(BatchJob.items))
            )
            if batch:
                aggregate_batch_job(session, batch)
            session.commit()
            invalidate_batch_status(batch.id if batch else item.batch_job_id, self._runtime_state)

    async def _run_suite_item(self, generation_job_id: str | None) -> None:
        if not generation_job_id:
            raise RuntimeError("Suite batch item is missing generation job")
        with self._session_factory() as session:
            job = session.get(GenerationJob, generation_job_id)
            if not job:
                raise RuntimeError("Suite generation job does not exist")
            has_failed_items = bool(
                session.scalar(
                    select(GenerationItem.id)
                    .where(GenerationItem.job_id == job.id, GenerationItem.status == "failed")
                    .limit(1)
                )
            )
            status = job.status
            dry_run = job.dry_run
        if status in FINAL_STATUSES and not has_failed_items:
            return
        if has_failed_items and not dry_run:
            await retry_failed_live_items(
                generation_job_id,
                self._session_factory,
                self._settings,
                self._cipher,
            )
            return
        await run_generation_job(
            generation_job_id,
            self._session_factory,
            self._settings,
            self._cipher,
        )

    async def _run_aplus_item(
        self,
        item_id: str,
        plan_job_id: str | None,
        generation_job_id: str | None,
    ) -> str | None:
        if not plan_job_id:
            raise RuntimeError("A+ batch item is missing plan job")
        with self._session_factory() as session:
            plan_job = session.get(AplusJob, plan_job_id)
            if not plan_job:
                raise RuntimeError("A+ plan job does not exist")
            plan_status = plan_job.status
        if plan_status != "succeeded":
            await run_aplus_plan_job(plan_job_id, self._session_factory, self._cipher)
        with self._session_factory() as session:
            plan_job = session.get(AplusJob, plan_job_id)
            item = session.get(BatchItem, item_id)
            if not plan_job or not item:
                raise RuntimeError("A+ batch item disappeared")
            if plan_job.status != "succeeded":
                item.status = "failed"
                item.error = plan_job.error or "A+ plan job failed"
                item.completed_at = utcnow()
                session.commit()
                return generation_job_id
            if not generation_job_id:
                generation_job = create_aplus_generation_for_batch_item(session, item)
                generation_job_id = generation_job.id
                session.commit()
                invalidate_batch_status(item.batch_job_id, self._runtime_state)
        with self._session_factory() as session:
            generation_job = session.get(AplusJob, generation_job_id)
            if not generation_job:
                raise RuntimeError("A+ generation job does not exist")
            has_failed_items = any(item.status == "failed" for item in generation_job.items)
            status = generation_job.status
        if status in FAILED_STATUSES or has_failed_items:
            await retry_failed_aplus_items(
                generation_job_id,
                self._session_factory,
                self._settings,
                self._cipher,
            )
        elif status not in FINAL_STATUSES:
            await run_aplus_generation_job(
                generation_job_id,
                self._session_factory,
                self._settings,
                self._cipher,
            )
        return generation_job_id
