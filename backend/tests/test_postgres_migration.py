from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.config import Settings
from backend.app.database import build_engine
from backend.app.models import User
from backend.scripts.migrate_sqlite_to_postgres import (
    ALLOWED_ORPHANS,
    SourceValidationError,
    TargetValidationError,
    _normalize_value,
    validate_target,
)


def test_database_engine_uses_postgres_pool_policy(postgres_database_url: str) -> None:
    settings = Settings(database_url=postgres_database_url, _env_file=None)

    engine = build_engine(settings)

    assert engine.dialect.name == "postgresql"
    assert engine.pool.size() == settings.database_pool_size
    assert engine.pool._max_overflow == settings.database_max_overflow
    assert engine.pool._recycle == settings.database_pool_recycle_seconds
    assert engine.pool._pre_ping is True
    engine.dispose()


def test_migration_normalizes_source_values_and_rejects_bad_data(
    postgres_database_url: str,
) -> None:
    settings = Settings(database_url=postgres_database_url, _env_file=None)
    timestamp = datetime(2026, 8, 23, 1, 2, 3)
    boolean_column = User.password_set
    datetime_column = User.last_login_at

    assert _normalize_value(timestamp, datetime_column) == timestamp.replace(tzinfo=timezone.utc)
    assert _normalize_value(1, boolean_column) is True
    assert _normalize_value(0, boolean_column) is False
    with pytest.raises(SourceValidationError):
        _normalize_value(2, boolean_column)
    assert settings.database_pool_size >= 1


def test_target_validation_rejects_non_empty_database(postgres_database_url: str) -> None:
    engine = create_engine(postgres_database_url)
    try:
        assert validate_target(engine, require_empty=True)["alembic_version"]
        with Session(engine) as session:
            session.add(
                User(
                    id="validation-user",
                    phone="13800138000",
                    username="validation-user",
                    display_name="Validation User",
                    uid="VALUSER",
                )
            )
            session.commit()

        with pytest.raises(TargetValidationError, match="app_user is not empty"):
            validate_target(engine, require_empty=True)
    finally:
        engine.dispose()


def test_orphan_whitelist_is_the_confirmed_execution_log_set() -> None:
    assert {row[0] for row in ALLOWED_ORPHANS} == {"execution_log"}
    assert {row[1] for row in ALLOWED_ORPHANS} == {
        "293faf5d-25ab-431a-a164-b7da48b58cc0",
        "3771430d-dcc7-4390-972b-54de2fe99f1d",
    }
    assert {row[2] for row in ALLOWED_ORPHANS} == {"job_id", "item_id"}
