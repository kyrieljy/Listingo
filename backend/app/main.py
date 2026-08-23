from contextlib import asynccontextmanager
import asyncio
import logging
import os
from time import monotonic

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from backend.app.config import Settings
from backend.app.core.rate_limit import SINGLE_PROCESS_WARNING, create_rate_limiter
from backend.app.core.storage.base import RateLimitStorage, StorageUnavailableError
from backend.app.database import build_engine, build_session_factory
from backend.app.middleware.ip_block import IPBlockMiddleware
from backend.app.models import Base
from backend.app.seed import seed_database
from backend.app.security import ApiKeyCipher
from backend.app.api.auth import router as auth_router
from backend.app.api.public import router as public_router
from backend.app.api.admin import router as admin_router
from backend.app.services.batch_scheduler import BatchScheduler
from backend.app.services.workspace_recovery import recover_interrupted_workspace_jobs, repair_monitoring_fixture_history


logger = logging.getLogger(__name__)


def _validate_single_worker(settings: Settings) -> None:
    if settings.storage_backend != "memory":
        return
    raw_concurrency = os.getenv("WEB_CONCURRENCY")
    if raw_concurrency is None or not raw_concurrency.strip():
        return
    try:
        concurrency = int(raw_concurrency)
    except ValueError as exc:
        raise RuntimeError(f"WEB_CONCURRENCY must be an integer, got {raw_concurrency!r}") from exc
    if concurrency < 1:
        raise RuntimeError("WEB_CONCURRENCY must be at least 1")
    if concurrency > 1 and not settings.testing:
        raise RuntimeError(
            "WEB_CONCURRENCY > 1 is incompatible with memory rate limiting. "
            "Use one worker and one instance, or configure a distributed storage backend."
        )


async def _wait_for_storage(storage: RateLimitStorage, timeout_seconds: float) -> None:
    deadline = monotonic() + timeout_seconds
    last_error: StorageUnavailableError | None = None
    while monotonic() < deadline:
        try:
            storage.ping()
            return
        except StorageUnavailableError as exc:
            last_error = exc
            await asyncio.sleep(min(0.25, max(0.01, deadline - monotonic())))
    raise RuntimeError(f"Redis is unavailable after {timeout_seconds:g}s") from last_error


def ensure_runtime_schema(engine: Engine) -> None:
    if engine.dialect.name != "sqlite":
        return
    with engine.begin() as connection:
        inspector = inspect(connection)
        for table_name in ("generation_job", "video_job", "aplus_job"):
            if not inspector.has_table(table_name):
                continue
            columns = {column["name"] for column in inspector.get_columns(table_name)}
            if "user_id" not in columns:
                connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN user_id VARCHAR(36)"))
                connection.execute(text(f"CREATE INDEX IF NOT EXISTS ix_{table_name}_user_id ON {table_name} (user_id)"))
            if "is_admin_test" not in columns:
                connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN is_admin_test BOOLEAN NOT NULL DEFAULT 0"))
        for table_name in ("asset", "batch_job"):
            if not inspector.has_table(table_name):
                continue
            columns = {column["name"] for column in inspector.get_columns(table_name)}
            if "user_id" not in columns:
                connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN user_id VARCHAR(36)"))
                connection.execute(text(f"CREATE INDEX IF NOT EXISTS ix_{table_name}_user_id ON {table_name} (user_id)"))
        if inspector.has_table("execution_log"):
            columns = {column["name"] for column in inspector.get_columns("execution_log")}
            if "dry_run" not in columns:
                connection.execute(text("ALTER TABLE execution_log ADD COLUMN dry_run BOOLEAN NOT NULL DEFAULT 1"))
        for table_name in ("generation_item", "aplus_item"):
            if not inspector.has_table(table_name):
                continue
            columns = {column["name"] for column in inspector.get_columns(table_name)}
            if "provider_task_id" not in columns:
                connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN provider_task_id VARCHAR(160)"))
                connection.execute(text(f"CREATE INDEX IF NOT EXISTS ix_{table_name}_provider_task_id ON {table_name} (provider_task_id)"))


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or Settings()
    _validate_single_worker(resolved)
    resolved.ensure_directories()
    rate_limiter = create_rate_limiter(resolved)
    engine = build_engine(resolved)
    session_factory = build_session_factory(engine)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> None:
        try:
            if resolved.storage_backend == "redis":
                await _wait_for_storage(rate_limiter.storage, resolved.redis_startup_timeout_seconds)
                logger.info("Rate limiting is using Redis with prefix %s", resolved.redis_key_prefix)
            else:
                logger.warning("\033[1;31m%s\033[0m", SINGLE_PROCESS_WARNING)
            if not resolved.testing:
                rate_limiter.start()
            Base.metadata.create_all(engine)
            ensure_runtime_schema(engine)
            with session_factory() as session:
                seed_database(session)
                repair_monitoring_fixture_history(session)
                recover_interrupted_workspace_jobs(session)
            scheduler = BatchScheduler(session_factory, resolved, application.state.cipher)
            application.state.batch_scheduler = scheduler
            if not resolved.testing:
                await scheduler.start()
            yield
        finally:
            if not resolved.testing and "scheduler" in locals():
                await scheduler.stop()
            try:
                rate_limiter.close()
            except StorageUnavailableError:
                logger.warning("Rate-limit storage could not be closed cleanly")
            engine.dispose()

    application = FastAPI(title="Listingo API", version="0.1.0", lifespan=lifespan)
    application.state.settings = resolved
    application.state.engine = engine
    application.state.session_factory = session_factory
    application.state.cipher = ApiKeyCipher(resolved.secret_key_path)
    application.state.rate_limiter = rate_limiter
    @application.exception_handler(StorageUnavailableError)
    async def storage_unavailable_handler(_: Request, __: StorageUnavailableError) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": "防护存储暂不可用，请稍后再试"})
    # IP blocking must sit inside CORS so browsers still receive CORS headers on 403.
    application.add_middleware(IPBlockMiddleware)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=resolved.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.mount("/files", StaticFiles(directory=resolved.data_dir), name="files")
    application.include_router(auth_router)
    application.include_router(public_router)
    application.include_router(admin_router)

    @application.get("/api/v1/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "mode": "dryrun-default"}

    return application


app = create_app()
