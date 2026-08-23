"""Copy a frozen SQLite Listingo database into an empty PostgreSQL schema."""

from __future__ import annotations

import argparse
from collections.abc import Iterator, Sequence
from datetime import date, datetime, time, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import uuid
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Boolean, DateTime, create_engine, func, inspect, select, text
from sqlalchemy.engine import Connection, Engine, make_url
from sqlalchemy.schema import Column, Table

from backend.app.config import Settings
from backend.app.models import Base

ALEMBIC_CONFIG_PATH = PROJECT_ROOT / "backend" / "alembic.ini"
DEFAULT_SOURCE = PROJECT_ROOT / "data" / "listingo.sqlite3"
DEFAULT_BACKUP_DIR = PROJECT_ROOT / "data" / "backups"
BATCH_SIZE = 500

ALLOWED_ORPHANS = {
    ("execution_log", "293faf5d-25ab-431a-a164-b7da48b58cc0", "job_id", "a7e2ea6c-df61-4599-8858-5bf40e76083e"),
    ("execution_log", "293faf5d-25ab-431a-a164-b7da48b58cc0", "item_id", "07af9d5e-2ba2-4b2b-972f-a89e03118b8c"),
    ("execution_log", "3771430d-dcc7-4390-972b-54de2fe99f1d", "job_id", "a7e2ea6c-df61-4599-8858-5bf40e76083e"),
    ("execution_log", "3771430d-dcc7-4390-972b-54de2fe99f1d", "item_id", "74545ce8-0a66-4515-bd08-3de90bdb0f21"),
}


class SourceValidationError(ValueError):
    pass


class TargetValidationError(RuntimeError):
    pass


class Snapshot:
    def __init__(self) -> None:
        self.rows: dict[str, list[dict[str, Any]]] = {}
        self.counts: dict[str, int] = {}
        self.digests: dict[str, str] = {}
        self.corrections: list[dict[str, str]] = []


def _head_revision() -> str:
    heads = ScriptDirectory.from_config(Config(str(ALEMBIC_CONFIG_PATH))).get_heads()
    if len(heads) != 1:
        raise TargetValidationError(f"Alembic has multiple heads: {', '.join(heads)}")
    return heads[0]


def _redacted_url(url: str) -> str:
    return make_url(url).render_as_string(hide_password=True)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source_file:
        for chunk in iter(lambda: source_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return aware.astimezone(timezone.utc).isoformat()
    if isinstance(value, (date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).hex()
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return str(value)


def _primary_key_values(table: Table, row: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(_canonical_value(row[column.name]) for column in table.primary_key.columns)


def _digest_rows(table: Table, rows: Sequence[dict[str, Any]]) -> str:
    ordered = sorted(rows, key=lambda row: _primary_key_values(table, row))
    canonical = json.dumps(
        [[_canonical_value(row[column.name]) for column in table.columns] for row in ordered],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _normalize_value(value: Any, column: Column) -> Any:
    if value is None:
        return None
    if isinstance(column.type, DateTime):
        if not isinstance(value, datetime):
            raise SourceValidationError(
                f"{column.table.name}.{column.name} expected datetime, got {type(value).__name__}"
            )
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(column.type, Boolean):
        if value not in (True, False, 0, 1):
            raise SourceValidationError(f"{column.table.name}.{column.name} expected boolean, got {value!r}")
        return bool(value)
    column_length = getattr(column.type, "length", None)
    if column_length is not None:
        if not isinstance(value, str):
            raise SourceValidationError(f"{column.table.name}.{column.name} expected text, got {type(value).__name__}")
        if len(value) > column_length:
            raise SourceValidationError(f"{column.table.name}.{column.name} length {len(value)} exceeds {column_length}")
    return value


def _iter_rows(connection: Connection, table: Table) -> Iterator[dict[str, Any]]:
    result = connection.execution_options(stream_results=True, max_row_buffer=BATCH_SIZE).execute(select(table))
    while batch := result.mappings().fetchmany(BATCH_SIZE):
        for row in batch:
            yield dict(row)


def capture_source(source_engine: Engine) -> Snapshot:
    if source_engine.dialect.name != "sqlite":
        raise SourceValidationError("source database must be SQLite")
    inspector = inspect(source_engine)
    source_tables = set(inspector.get_table_names())
    missing_tables = sorted(set(Base.metadata.tables) - source_tables)
    if missing_tables:
        raise SourceValidationError(f"source is missing tables: {', '.join(missing_tables)}")

    snapshot = Snapshot()
    with source_engine.connect() as connection:
        primary_keys: dict[tuple[str, str], set[Any]] = {}
        for table in Base.metadata.sorted_tables:
            source_columns = {column["name"] for column in inspector.get_columns(table.name)}
            missing_columns = sorted(set(table.columns.keys()) - source_columns)
            if missing_columns:
                raise SourceValidationError(
                    f"source table {table.name} is missing columns: {', '.join(missing_columns)}"
                )
            rows: list[dict[str, Any]] = []
            for raw_row in _iter_rows(connection, table):
                row = {
                    column.name: _normalize_value(raw_row.get(column.name), column)
                    for column in table.columns
                }
                for column in table.columns:
                    if not column.nullable and row[column.name] is None:
                        raise SourceValidationError(f"{table.name}.{column.name} contains NULL")
                rows.append(row)
            for column in table.primary_key.columns:
                primary_keys[(table.name, column.name)] = {row[column.name] for row in rows}
            snapshot.rows[table.name] = rows
            snapshot.counts[table.name] = len(rows)
            snapshot.digests[table.name] = _digest_rows(table, rows)

        seen_orphans: set[tuple[str, str, str, Any]] = set()
        for table in Base.metadata.sorted_tables:
            for foreign_key in table.foreign_keys:
                target_key = (foreign_key.column.table.name, foreign_key.column.name)
                target_values = primary_keys.get(target_key)
                if target_values is None:
                    raise SourceValidationError(f"cannot resolve foreign key {foreign_key}")
                for row in snapshot.rows[table.name]:
                    value = row[foreign_key.parent.name]
                    if value is None or value in target_values:
                        continue
                    orphan = (table.name, str(row["id"]), foreign_key.parent.name, value)
                    if orphan not in ALLOWED_ORPHANS:
                        raise SourceValidationError(
                            f"unresolved foreign key: {table.name}.{foreign_key.parent.name}={value!r}"
                        )
                    seen_orphans.add(orphan)
                    row[foreign_key.parent.name] = None
                    snapshot.corrections.append(
                        {
                            "table": table.name,
                            "id": str(row["id"]),
                            "column": foreign_key.parent.name,
                            "original_value": str(value),
                        }
                    )

        if seen_orphans != ALLOWED_ORPHANS:
            missing_expected = ALLOWED_ORPHANS - seen_orphans
            if missing_expected:
                raise SourceValidationError("expected historical execution_log orphan rows are no longer present")

        for table in Base.metadata.sorted_tables:
            snapshot.digests[table.name] = _digest_rows(table, snapshot.rows[table.name])

    return snapshot


def _target_metadata_diff(connection: Connection) -> list[Any]:
    context = MigrationContext.configure(connection)
    return compare_metadata(context, Base.metadata)


def validate_target(target_engine: Engine, *, require_empty: bool) -> dict[str, Any]:
    if target_engine.dialect.name != "postgresql":
        raise TargetValidationError("target database must be PostgreSQL")
    inspector = inspect(target_engine)
    tables = set(inspector.get_table_names())
    if "alembic_version" not in tables:
        raise TargetValidationError("target schema is not initialized")
    missing = sorted(set(Base.metadata.tables) - tables)
    if missing:
        raise TargetValidationError(f"target is missing tables: {', '.join(missing)}")
    if "sms_verification_code" in tables:
        raise TargetValidationError("legacy sms_verification_code table must not exist")

    with target_engine.connect() as connection:
        version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
        expected_version = _head_revision()
        if version != expected_version:
            raise TargetValidationError(f"target Alembic version is {version!r}, expected {expected_version!r}")
        differences = _target_metadata_diff(connection)
        if differences:
            raise TargetValidationError(f"target schema differs from ORM metadata: {differences!r}")
        counts: dict[str, int] = {}
        for table in Base.metadata.sorted_tables:
            count = int(connection.execute(select(func.count()).select_from(table)).scalar_one())
            counts[table.name] = count
            if require_empty and count:
                raise TargetValidationError(f"target table {table.name} is not empty")

    return {"alembic_version": str(version), "counts": counts}


def capture_target(target_engine: Engine) -> Snapshot:
    snapshot = Snapshot()
    with target_engine.connect() as connection:
        for table in Base.metadata.sorted_tables:
            rows = [dict(row) for row in connection.execute(select(table)).mappings()]
            snapshot.rows[table.name] = rows
            snapshot.counts[table.name] = len(rows)
            snapshot.digests[table.name] = _digest_rows(table, rows)
    return snapshot


def verify_snapshots(source: Snapshot, target: Snapshot) -> None:
    if source.counts != target.counts:
        raise TargetValidationError(f"row count mismatch: source={source.counts}, target={target.counts}")
    if source.digests != target.digests:
        changed = [name for name in source.digests if source.digests[name] != target.digests.get(name)]
        raise TargetValidationError(f"row digest mismatch in: {', '.join(changed)}")


def backup_sqlite(source: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = backup_dir / f"listingo-{timestamp}.sqlite3"
    with sqlite3.connect(source) as source_connection, sqlite3.connect(backup_path) as backup_connection:
        source_connection.backup(backup_connection)
    return backup_path


def copy_snapshot(target_engine: Engine, source: Snapshot) -> None:
    with target_engine.begin() as connection:
        for table in Base.metadata.sorted_tables:
            connection.execute(text(f'LOCK TABLE "{table.name}" IN ACCESS EXCLUSIVE MODE'))
            count = int(connection.execute(select(func.count()).select_from(table)).scalar_one())
            if count:
                raise TargetValidationError(f"target table {table.name} became non-empty during migration")
        for table in Base.metadata.sorted_tables:
            rows = source.rows[table.name]
            for start in range(0, len(rows), BATCH_SIZE):
                connection.execute(table.insert(), rows[start : start + BATCH_SIZE])

        for table in Base.metadata.sorted_tables:
            rows = [dict(row) for row in connection.execute(select(table)).mappings()]
            digest = _digest_rows(table, rows)
            if len(rows) != source.counts[table.name] or digest != source.digests[table.name]:
                raise TargetValidationError(f"post-copy verification failed for {table.name}")

        invalid_constraints = connection.execute(
            text(
                "SELECT conname FROM pg_constraint "
                "WHERE connamespace = 'public'::regnamespace AND contype = 'f' AND NOT convalidated"
            )
        ).scalars().all()
        if invalid_constraints:
            raise TargetValidationError(f"invalid foreign key constraints: {', '.join(invalid_constraints)}")


def _write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    source = Path(args.source).resolve()
    target_url = args.target_url or Settings().resolved_database_url
    source_hash_before = _file_sha256(source)
    report: dict[str, Any] = {
        "status": "running",
        "mode": "check-only" if args.check_only else "verify-only" if args.verify_only else "copy",
        "source": str(source),
        "source_sha256": source_hash_before,
        "target_url": _redacted_url(target_url),
    }
    try:
        source_engine = create_engine(f"sqlite:///{source.as_posix()}")
        normalized_target_url = Settings(database_url=target_url, _env_file=None).resolved_database_url
        target_engine = create_engine(
            normalized_target_url,
            connect_args={"application_name": "listingo-migration", "connect_timeout": 10},
        )
        source_snapshot = capture_source(source_engine)
        target_info = validate_target(target_engine, require_empty=not args.verify_only)
        report.update(
            {
                "source_counts": source_snapshot.counts,
                "source_digests": source_snapshot.digests,
                "corrections": source_snapshot.corrections,
                "target_alembic_version": target_info["alembic_version"],
            }
        )
        if args.check_only:
            report["status"] = "passed"
        elif args.verify_only:
            target_snapshot = capture_target(target_engine)
            verify_snapshots(source_snapshot, target_snapshot)
            report.update({"status": "passed", "target_counts": target_snapshot.counts, "target_digests": target_snapshot.digests})
        else:
            backup_path = backup_sqlite(source, Path(args.backup_dir).resolve())
            if _file_sha256(source) != source_hash_before:
                raise RuntimeError("source SQLite file changed during migration preparation")
            report["backup_path"] = str(backup_path)
            report["backup_sha256"] = _file_sha256(backup_path)
            copy_snapshot(target_engine, source_snapshot)
            target_snapshot = capture_target(target_engine)
            verify_snapshots(source_snapshot, target_snapshot)
            report.update({"status": "passed", "target_counts": target_snapshot.counts, "target_digests": target_snapshot.digests})
        if _file_sha256(source) != source_hash_before:
            raise RuntimeError("source SQLite file changed during migration")
    except Exception as exc:
        report["status"] = "failed"
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["completed_at"] = datetime.now(timezone.utc).isoformat()
        _write_report(Path(args.report).resolve(), report)
        raise

    report["completed_at"] = datetime.now(timezone.utc).isoformat()
    _write_report(Path(args.report).resolve(), report)
    print(json.dumps({"status": report["status"], "report": str(Path(args.report).resolve())}))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default=str(DEFAULT_SOURCE))
    parser.add_argument("--target-url", help="PostgreSQL URL; defaults to LISTINGO_DATABASE_URL")
    parser.add_argument("--backup-dir", default=str(DEFAULT_BACKUP_DIR))
    parser.add_argument("--report", default=str(DEFAULT_BACKUP_DIR / "migration-report.json"))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check-only", action="store_true")
    mode.add_argument("--verify-only", action="store_true")
    return parser


def main() -> int:
    return run(build_parser().parse_args())


if __name__ == "__main__":
    sys.exit(main())
