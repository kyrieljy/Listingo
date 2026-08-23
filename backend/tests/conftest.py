from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.main import create_app


@pytest.fixture()
def client(tmp_path: Path) -> Generator[TestClient, None, None]:
    settings = Settings(
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{(tmp_path / 'data' / 'test.sqlite3').as_posix()}",
        testing=True,
        storage_backend="memory",
    )
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client

