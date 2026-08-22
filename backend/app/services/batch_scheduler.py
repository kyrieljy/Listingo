from __future__ import annotations

import asyncio
from contextlib import suppress

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker, selectinload

from backend.app.config import Settings
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
    sync_batch_item_from_children,
)
from backend.app.services.jobs import retry_failed_live_items, run_generation_job


class BatchScheduler:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        settings: Settings,
        cipher: ApiKeyCipher,
        *,
        poll_interval_seconds: float = 2.0,
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._cipher = cipher
        self._poll_interval_seconds = poll_interval_seconds
        self._loop_task: asyncio.Task[None] | None = None
        self._workers: set[asyncio.Task[None]] = set()
        self._stopping = asyncio.Event()

    async def start(self) -> None:
        self.recover()
        if self._loop_task is None or self._loop_task.done():
            self._stopping.clear()
            self._loop_task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        self._stopping.set()
        if self._loop_task:
            self._loop_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._loop_task
        if self._workers:
            await asyncio.gather(*self._workers, return_exceptions=True)

    def recover(self) -> None:
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

    async def tick(self, *, wait: bool = True) -> None:
        while True:
            await self._claim_available()
            if not wait:
                return
            if self._workers:
                await asyncio.gather(*list(self._workers), return_exceptions=True)
            with self._session_factory() as session:
                has_queued = bool(
                    session.scalar(
                        select(BatchItem.id)
                        .join(BatchJob, BatchJob.id == BatchItem.batch_job_id)
                        .where(BatchItem.status == "queued", BatchJob.status.in_(["queued", "running"]))
                        .limit(1)
                    )
                )
            if not has_queued:
                return

    async def _run_loop(self) -> None:
        while not self._stopping.is_set():
            await self.tick(wait=False)
            await asyncio.sleep(self._poll_interval_seconds)

    async def _claim_available(self) -> None:
        with self._session_factory() as session:
            self._sync_open_batches(session)
            db_running = int(session.scalar(select(func.count()).select_from(BatchItem).where(BatchItem.status == "running")) or 0)
            capacity = max(0, self._settings.max_active_batch_items - db_running - len(self._workers))
            if capacity <= 0:
                session.commit()
                return
            items = session.scalars(
                select(BatchItem)
                .join(BatchJob, BatchJob.id == BatchItem.batch_job_id)
                .where(BatchItem.status == "queued", BatchJob.status.in_(["queued", "running"]))
                .order_by(BatchJob.created_at, BatchItem.index)
                .limit(capacity)
                .options(selectinload(BatchItem.batch_job))
            ).all()
            item_ids: list[str] = []
            for item in items:
                batch = item.batch_job
                item.status = "running"
                item.started_at = item.started_at or utcnow()
                item.completed_at = None
                item.error = None
                batch.status = "running"
                batch.started_at = batch.started_at or utcnow()
                item_ids.append(item.id)
            session.commit()

        for item_id in item_ids:
            task = asyncio.create_task(self._run_item(item_id))
            self._workers.add(task)
            task.add_done_callback(self._workers.discard)

    def _sync_open_batches(self, session: Session) -> None:
        batches = session.scalars(
            select(BatchJob)
            .where(BatchJob.status.not_in(FINAL_STATUSES))
            .options(selectinload(BatchJob.items))
        ).all()
        for batch in batches:
            for item in batch.items:
                sync_batch_item_from_children(session, item)
            aggregate_batch_job(session, batch)

    async def _run_item(self, item_id: str) -> None:
        try:
            with self._session_factory() as session:
                item = session.get(BatchItem, item_id)
                if not item:
                    return
                batch = session.get(BatchJob, item.batch_job_id)
                if not batch or batch.status == "cancelling":
                    item.status = "cancelled"
                    item.error = "Batch is cancelling"
                    item.completed_at = utcnow()
                    session.commit()
                    return
                business_type = batch.business_type
                generation_job_id = item.generation_job_id
                aplus_plan_job_id = item.aplus_plan_job_id
                aplus_generation_job_id = item.aplus_generation_job_id

            if business_type == "suite":
                await self._run_suite_item(generation_job_id)
            else:
                aplus_generation_job_id = await self._run_aplus_item(item_id, aplus_plan_job_id, aplus_generation_job_id)

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
                    select(BatchJob).where(BatchJob.id == item.batch_job_id).options(selectinload(BatchJob.items))
                )
                if batch:
                    aggregate_batch_job(session, batch)
                session.commit()
        except Exception as exc:
            with self._session_factory() as session:
                item = session.get(BatchItem, item_id)
                if item:
                    item.status = "failed"
                    item.error = str(exc)
                    item.completed_at = utcnow()
                    batch = session.scalar(
                        select(BatchJob).where(BatchJob.id == item.batch_job_id).options(selectinload(BatchJob.items))
                    )
                    if batch:
                        aggregate_batch_job(session, batch)
                    session.commit()

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
            await retry_failed_live_items(generation_job_id, self._session_factory, self._settings, self._cipher)
            return
        await run_generation_job(generation_job_id, self._session_factory, self._settings, self._cipher)

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
        with self._session_factory() as session:
            generation_job = session.get(AplusJob, generation_job_id)
            if not generation_job:
                raise RuntimeError("A+ generation job does not exist")
            has_failed_items = any(item.status == "failed" for item in generation_job.items)
            status = generation_job.status
        if status in FINAL_STATUSES and not has_failed_items:
            return generation_job_id
        if status in FAILED_STATUSES or has_failed_items:
            await retry_failed_aplus_items(generation_job_id, self._session_factory, self._settings, self._cipher)
        else:
            await run_aplus_generation_job(generation_job_id, self._session_factory, self._settings, self._cipher)
        return generation_job_id
