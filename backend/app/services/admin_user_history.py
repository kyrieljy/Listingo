from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from fastapi import HTTPException
from sqlalchemy import exists, literal, or_, select, union_all
from sqlalchemy.orm import Session, aliased, selectinload

from backend.app.models import (
    AplusItem, AplusJob, BatchItem, BatchJob, CopywritingRecord, ExecutionLog,
    GenerationItem, GenerationJob,
)

HistoryKind = Literal["suite", "aplus", "batch"]


def read_object(raw: str) -> dict:
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def list_history(session: Session, user_id: str, offset: int, limit: int) -> dict:
    def standalone(model, kind, *links):
        in_batch = exists(
            select(BatchItem.id).join(BatchJob).where(
                BatchJob.user_id == user_id,
                or_(*(link == model.id for link in links)),
            )
        )
        return select(
            literal(kind).label("kind"), model.id, model.created_at, model.status, model.count,
        ).where(model.user_id == user_id, ~in_batch, model.is_admin_test.is_(False))

    generated_aplus = aliased(AplusJob)
    has_generation = exists(select(generated_aplus.id).where(
        generated_aplus.source_plan_job_id == AplusJob.id,
        generated_aplus.user_id == user_id,
        generated_aplus.is_admin_test.is_(False),
    ))
    history = union_all(
        standalone(GenerationJob, "suite", BatchItem.generation_job_id),
        standalone(AplusJob, "aplus", BatchItem.aplus_plan_job_id, BatchItem.aplus_generation_job_id).where(~has_generation),
        select(
            literal("batch"), BatchJob.id, BatchJob.created_at, BatchJob.status, BatchJob.total_count,
        ).where(BatchJob.user_id == user_id),
    ).subquery()
    rows = session.execute(
        select(history).order_by(history.c.created_at.desc(), history.c.id.desc()).offset(offset).limit(limit + 1)
    ).mappings().all()
    return {"items": [dict(row) for row in rows[:limit]], "has_more": len(rows) > limit}


def _owned_job(session: Session, kind: HistoryKind, user_id: str, job_id: str):
    model, item = (GenerationJob, GenerationItem) if kind == "suite" else (AplusJob, AplusItem)
    return session.scalar(
        select(model).where(model.id == job_id, model.user_id == user_id, model.is_admin_test.is_(False))
        .options(selectinload(model.items).selectinload(item.versions))
    )


def _job_detail(session: Session, kind: HistoryKind, job, data_dir: Path) -> dict:
    is_suite = kind == "suite"
    source = job
    if not is_suite and job.source_plan_job_id:
        source = session.scalar(select(AplusJob).where(
            AplusJob.id == job.source_plan_job_id, AplusJob.user_id == job.user_id,
            AplusJob.job_type == "plan", AplusJob.is_admin_test.is_(False),
        )) or job
    params = read_object(source.params_json)
    actual_input = params.get("selling_points" if is_suite else "product_info")
    record_id = params.get("copywriting_record_id")
    rewrite = session.get(CopywritingRecord, record_id) if isinstance(record_id, str) else None
    if rewrite and rewrite.user_id != job.user_id:
        rewrite = None

    link = ExecutionLog.job_id if is_suite else ExecutionLog.aplus_job_id
    logs = session.scalars(
        select(ExecutionLog).where(link.in_({job.id, source.id}))
        .order_by(ExecutionLog.created_at, ExecutionLog.id)
    )
    steps = []
    for log in logs:
        data = read_object(log.request_summary)
        steps.append({
            "node": log.node, "status": log.status, "created_at": log.created_at,
            "error": log.error, "prompt": data.get("image_prompt") if log.node == "image_model_prompt" else None,
            "item_id": data.get("item_id") if log.node == "image_model_prompt" else log.item_id,
            "instruction": data.get("instruction") if log.node == "image_model_prompt" else None,
        })

    items = []
    for item in job.items:
        versions = []
        for version in item.versions:
            path = Path(version.file_path).resolve() if version.file_path else None
            available = bool(path and path.is_relative_to(data_dir) and path.is_file())
            versions.append({
                "id": version.id, "version_no": version.version_no, "instruction": version.instruction,
                "url": version.url if available else None,
            })
        items.append({
            "id": item.id, "label": item.image_type if is_suite else item.module_name,
            "status": item.status, "error": item.error,
            "planned_prompt": item.prompt_text or None, "versions": versions,
        })
    return {
        "id": job.id, "status": job.status, "error": job.error, "dry_run": job.dry_run,
        "input": rewrite.original_input if rewrite else actual_input,
        "submitted_input": actual_input,
        "rewrite": rewrite.rewritten_text if rewrite else None,
        "rewrite_recorded": "copywriting_record_id" in params,
        "steps": steps, "items": items,
        "source_plan_id": source.id if source is not job else None,
    }


def history_detail(session: Session, user_id: str, kind: HistoryKind, job_id: str, data_dir: Path) -> dict:
    if kind == "batch":
        batch = session.scalar(
            select(BatchJob).where(BatchJob.id == job_id, BatchJob.user_id == user_id)
            .options(selectinload(BatchJob.items))
        )
        if batch:
            def owned_ids(model, ids):
                return set(session.scalars(select(model.id).where(
                    model.id.in_(ids), model.user_id == user_id, model.is_admin_test.is_(False),
                ))) if ids else set()

            suite_ids = owned_ids(GenerationJob, {item.generation_job_id for item in batch.items if item.generation_job_id})
            aplus_ids = owned_ids(AplusJob, {
                job_id for item in batch.items for job_id in (item.aplus_plan_job_id, item.aplus_generation_job_id) if job_id
            })
            children = []
            for item in batch.items:
                child_id = item.generation_job_id or item.aplus_generation_job_id or item.aplus_plan_job_id
                child_kind = "suite" if item.generation_job_id else "aplus"
                visible = child_id in (suite_ids if child_kind == "suite" else aplus_ids)
                children.append({
                    "id": item.id, "name": item.name, "status": item.status, "error": item.error,
                    "job_kind": child_kind if visible else None, "job_id": child_id if visible else None,
                })
            return {"id": batch.id, "status": batch.status, "error": batch.error, "children": children}
    else:
        job = _owned_job(session, kind, user_id, job_id)
        if job:
            return _job_detail(session, kind, job, data_dir.resolve())
    raise HTTPException(status_code=404, detail="Task not found")
