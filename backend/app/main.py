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
from backend.app.api.public import router as public_router
from backend.app.api.admin import router as admin_router


def ensure_runtime_schema(engine) -> None:
    if engine.dialect.name != "sqlite":
        return
    with engine.begin() as connection:
        inspector = inspect(connection)
        for table_name in ("generation_job", "video_job", "aplus_job"):
            if not inspector.has_table(table_name):
                continue
            columns = {column["name"] for column in inspector.get_columns(table_name)}
            if "is_admin_test" not in columns:
                connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN is_admin_test BOOLEAN NOT NULL DEFAULT 0"))


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
        yield
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
    application.include_router(public_router)
    application.include_router(admin_router)

    @application.get("/api/v1/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "mode": "dryrun-default"}

    return application


app = create_app()
