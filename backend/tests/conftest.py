from __future__ import annotations

from collections.abc import Generator
import os
from pathlib import Path
import uuid

from alembic import command
from alembic.config import Config
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from backend.app.config import Settings
from backend.app.main import create_app
from backend.app.models import Base


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_CONFIG = PROJECT_ROOT / "backend" / "alembic.ini"
DEFAULT_TEST_ADMIN_URL = "postgresql://postgres:admin@localhost:5432/postgres"


@pytest.fixture(scope="session")
def postgres_database_url():
    admin_url = make_url(os.getenv("LISTINGO_TEST_DATABASE_URL", DEFAULT_TEST_ADMIN_URL))
    database_name = f"listingo_test_{uuid.uuid4().hex}"
    test_url = admin_url.set(database=database_name)
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{database_name}"'))

        previous_url = os.environ.get("LISTINGO_DATABASE_URL")
        os.environ["LISTINGO_DATABASE_URL"] = test_url.render_as_string(hide_password=False)
        command.upgrade(Config(str(ALEMBIC_CONFIG)), "head")
        yield test_url.render_as_string(hide_password=False)

        command.downgrade(Config(str(ALEMBIC_CONFIG)), "base")
        command.upgrade(Config(str(ALEMBIC_CONFIG)), "head")

        with admin_engine.connect() as connection:
            connection.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :database_name AND pid <> pg_backend_pid()"
                ),
                {"database_name": database_name},
            )
            connection.execute(text(f'DROP DATABASE "{database_name}"'))
    finally:
        if previous_url is None:
            os.environ.pop("LISTINGO_DATABASE_URL", None)
        else:
            os.environ["LISTINGO_DATABASE_URL"] = previous_url
        admin_engine.dispose()


@pytest.fixture(autouse=True)
def clean_business_tables(postgres_database_url: str) -> None:
    _clear_business_tables(postgres_database_url)


def _clear_business_tables(database_url: str) -> None:
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            table_names = ", ".join(f'"{table.name}"' for table in reversed(Base.metadata.sorted_tables))
            connection.execute(text(f"TRUNCATE TABLE {table_names} RESTART IDENTITY CASCADE"))
    finally:
        engine.dispose()


@pytest.fixture()
def client(tmp_path: Path, postgres_database_url: str) -> Generator[TestClient, None, None]:
    settings = Settings(
        data_dir=tmp_path / "data",
        database_url=postgres_database_url,
        testing=True,
        storage_backend="memory",
        _env_file=None,
    )
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client

