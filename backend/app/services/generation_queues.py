from __future__ import annotations

"""Sequential Redis-backed queues for ordinary suite and video generation jobs."""

import asyncio
from contextlib import suppress
import logging
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker, selectinload

from backend.app.config import Settings
from backend.app.core.runtime import RuntimeStateService
from backend.app.core.storage.base import StorageUnavailableError
from backend.app.core.storage.keys import lock_key, queue_key
from backend.app.models import (
    BatchItem,
    GenerationJob,
    VideoJob,
    utcnow,
)
from backend.app.security import ApiKeyCipher
from backend.app.services.jobs import retry_failed_live_items, run_generation_job
from backend.app.services.notifications import create_job_result_notification_once
from backend.app.services.video_jobs import run_video_job


logger = logging.getLogger(__name__)
QueueKind = Literal["generation", "video"]
QUEUE_KINDS: tuple[QueueKind, ...] = ("generation", "video")
NOTIFIED_STATUSES = {"succeeded", "partial_failed", "failed"}


class GenerationQueueScheduler:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        settings: Settings,
        cipher: ApiKeyCipher,
        *,
        runtime_state: RuntimeStateService,
        poll_interval_seconds: float | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._cipher = cipher
        self._runtime_state = runtime_state
        self._storage = runtime_state.storage
        self._poll_interval_seconds = (
            poll_interval_seconds
            if poll_interval_seconds is not None
            else settings.generation_queue_poll_interval_seconds
        )
        self._worker_tasks: dict[QueueKind, asyncio.Task[None]] = {}
        self._stopping = asyncio.Event()

    @property
    def storage(self):
        return self._storage

    def enqueue(self, kind: QueueKind, job_id: str) -> None:
        self._storage.queue_push(queue_key(kind), job_id)

    def remove(self, kind: QueueKind, job_id: str) -> bool:
        return self._storage.queue_remove(queue_key(kind), job_id)

    def queue_length(self, kind: QueueKind) -> int:
        return self._storage.queue_length(queue_key(kind))

    def queue_items(self, kind: QueueKind) -> list[str]:
        return self._storage.queue_items(queue_key(kind))

    def rebuild(self) -> dict[QueueKind, int]:
        """Clear runtime queues and restore FIFO order from PostgreSQL facts."""
        counts: dict[QueueKind, int] = {}
        with self._session_factory() as session:
            batch_generation_ids = select(BatchItem.generation_job_id).where(
                BatchItem.generation_job_id.is_not(None)
            )
            generation_ids = session.scalars(
                select(GenerationJob.id)
                .where(
                    GenerationJob.status == "queued",
                    GenerationJob.is_admin_test.is_(False),
                    GenerationJob.user_id.is_not(None),
                    ~GenerationJob.id.in_(batch_generation_ids),
                )
                .order_by(GenerationJob.created_at, GenerationJob.id)
            ).all()
            video_ids = session.scalars(
                select(VideoJob.id)
                .where(
                    VideoJob.status == "queued",
                    VideoJob.is_admin_test.is_(False),
                    VideoJob.user_id.is_not(None),
                )
                .order_by(VideoJob.created_at, VideoJob.id)
            ).all()

        for kind, job_ids in (("generation", generation_ids), ("video", video_ids)):
            key = queue_key(kind)
            self._storage.queue_clear(key)
            for job_id in job_ids:
                self._storage.queue_push(key, job_id)
            counts[kind] = len(job_ids)
        return counts

    def reconcile_notifications(self) -> int:
        """Compensate terminal jobs whose notification transaction was interrupted."""
        created = 0
        try:
            with self._session_factory() as session:
                for kind in QUEUE_KINDS:
                    model = GenerationJob if kind == "generation" else VideoJob
                    jobs = session.scalars(
                        select(model).where(
                            model.status.in_(NOTIFIED_STATUSES),
                            model.is_admin_test.is_(False),
                            model.user_id.is_not(None),
                        )
                    ).all()
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
        except Exception:
            logger.warning("Generation queue notification compensation failed", exc_info=True)
            return created
        return created

    async def start(self) -> None:
        self.rebuild()
        self.reconcile_notifications()
        self._stopping.clear()
        for kind in QUEUE_KINDS:
            if kind not in self._worker_tasks or self._worker_tasks[kind].done():
                self._worker_tasks[kind] = asyncio.create_task(
                    self._run_loop(kind),
                    name=f"generation-queue-{kind}",
                )

    async def stop(self) -> None:
        self._stopping.set()
        tasks = list(self._worker_tasks.values())
        if tasks:
            done, pending = await asyncio.wait(
                tasks,
                timeout=self._settings.generation_queue_stop_timeout_seconds,
            )
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

    async def tick(self, kind: QueueKind) -> bool:
        """Claim and execute at most one queued job; return whether an element was consumed."""
        job_id = self._storage.queue_pop(queue_key(kind))
        if job_id is None:
            return False

        retry_generation = False
        with self._session_factory() as session:
            job = session.scalar(
                select(GenerationJob if kind == "generation" else VideoJob)
                .where(GenerationJob.id == job_id if kind == "generation" else VideoJob.id == job_id)
                .with_for_update()
            )
            if not job or job.status != "queued":
                session.commit()
                return True
            if kind == "generation":
                retry_generation = any(item.status == "failed" for item in job.items)
            job.status = "running"
            job.started_at = job.started_at or utcnow()
            job.completed_at = None
            job.error = None
            session.commit()

        try:
            if kind == "generation":
                if retry_generation:
                    await retry_failed_live_items(
                        job_id,
                        self._session_factory,
                        self._settings,
                        self._cipher,
                    )
                else:
                    await run_generation_job(
                        job_id,
                        self._session_factory,
                        self._settings,
                        self._cipher,
                    )
            else:
                await run_video_job(
                    job_id,
                    self._session_factory,
                    self._settings,
                    self._cipher,
                )
        except Exception as exc:
            logger.exception("Queued generation job %s %s failed", kind, job_id)
            self._mark_claim_failed(kind, job_id, str(exc))

        self._notify_terminal(kind, job_id)
        return True

    def _mark_claim_failed(self, kind: QueueKind, job_id: str, error: str) -> None:
        model = GenerationJob if kind == "generation" else VideoJob
        with self._session_factory() as session:
            job = session.scalar(
                select(model)
                .where(model.id == job_id)
                .options(selectinload(model.items))
            )
            if not job or job.status != "running":
                return
            job.status = "failed"
            job.error = error
            job.completed_at = utcnow()
            for item in job.items:
                if item.status in {"queued", "running"}:
                    item.status = "failed"
                    item.error = error
            if kind == "generation":
                from backend.app.services.jobs import sync_generation_quota

                sync_generation_quota(session, job)
            else:
                from backend.app.services.video_jobs import sync_video_quota

                sync_video_quota(session, job)
            session.commit()

    def _notify_terminal(self, kind: QueueKind, job_id: str) -> None:
        model = GenerationJob if kind == "generation" else VideoJob
        try:
            with self._session_factory() as session:
                job = session.get(model, job_id)
                if not job or not job.user_id or job.status not in NOTIFIED_STATUSES:
                    return
                create_job_result_notification_once(
                    session,
                    job.user_id,
                    category=kind,
                    job_id=job.id,
                    status=job.status,
                    dry_run=job.dry_run,
                )
                session.commit()
        except Exception:
            logger.warning("Queued job terminal notification failed: %s %s", kind, job_id, exc_info=True)

    async def _run_loop(self, kind: QueueKind) -> None:
        lease_key = lock_key("generation-queue", kind)
        while not self._stopping.is_set():
            token: str | None = None
            try:
                token = self._runtime_state.acquire_lock(
                    lease_key,
                    self._runtime_state.ttls.lock,
                )
            except StorageUnavailableError:
                logger.warning("Generation queue lease acquisition failed", exc_info=True)
            if token is None:
                await self._sleep(self._poll_interval_seconds)
                continue

            lease_lost = asyncio.Event()
            renewal_task = asyncio.create_task(
                self._renew_lease(lease_key, token, lease_lost),
                name=f"generation-queue-{kind}-lease",
            )
            try:
                while not self._stopping.is_set() and not lease_lost.is_set():
                    try:
                        processed = await self.tick(kind)
                    except StorageUnavailableError:
                        logger.warning("Generation queue storage failed", exc_info=True)
                        break
                    if not processed:
                        await self._sleep(self._poll_interval_seconds)
            finally:
                renewal_task.cancel()
                with suppress(asyncio.CancelledError):
                    await renewal_task
                with suppress(StorageUnavailableError):
                    self._runtime_state.release_lock(lease_key, token)

    async def _renew_lease(self, key: str, token: str, lease_lost: asyncio.Event) -> None:
        interval = max(0.1, self._runtime_state.ttls.lock / 3)
        while True:
            await asyncio.sleep(interval)
            try:
                if not self._runtime_state.renew_lock(
                    key,
                    token,
                    self._runtime_state.ttls.lock,
                ):
                    lease_lost.set()
                    return
            except StorageUnavailableError:
                logger.warning("Generation queue lease renewal failed", exc_info=True)
                lease_lost.set()
                return

    async def _sleep(self, seconds: float) -> None:
        with suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self._stopping.wait(), timeout=seconds)
