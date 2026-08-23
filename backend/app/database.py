from __future__ import annotations

from collections.abc import Generator

from fastapi import Request
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from backend.app.config import Settings


def build_engine(settings: Settings) -> Engine:
    return create_engine(
        settings.resolved_database_url,
        connect_args={
            "application_name": "listingo",
            "connect_timeout": 10,
            "keepalives": 1,
            "keepalives_idle": 30,
            "keepalives_interval": 10,
            "keepalives_count": 5,
        },
        pool_pre_ping=True,
        pool_recycle=settings.database_pool_recycle_seconds,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        future=True,
    )


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, class_=Session, expire_on_commit=False, autoflush=False)


def get_session(request: Request) -> Generator[Session, None, None]:
    session = request.app.state.session_factory()
    try:
        yield session
    finally:
        session.close()

