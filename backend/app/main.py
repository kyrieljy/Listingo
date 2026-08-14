from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import inspect, text

from backend.app.config import Settings
from backend.app.database import build_engine, build_session_factory
from backend.app.models import Base
from backend.app.seed import seed_database
from backend.app.security import ApiKeyCipher
from backend.app.api.auth import router as auth_router
from backend.app.api.public import router as public_router
from backend.app.api.admin import router as admin_router
from backend.app.services.batch_scheduler import BatchScheduler
from backend.app.services.workspace_recovery import recover_interrupted_workspace_jobs, repair_monitoring_fixture_history


def ensure_runtime_schema(engine) -> None:
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
    resolved.ensure_directories()
    engine = build_engine(resolved)
    session_factory = build_session_factory(engine)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
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
        await scheduler.stop()
        engine.dispose()

    application = FastAPI(title="Listingo API", version="0.1.0", lifespan=lifespan)
    application.state.settings = resolved
    application.state.engine = engine
    application.state.session_factory = session_factory
    application.state.cipher = ApiKeyCipher(resolved.secret_key_path)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
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
