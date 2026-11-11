from __future__ import annotations

import json

from sqlalchemy.orm import Session

from backend.app.models import ExecutionLog


def record_image_prompt(
    session: Session,
    *,
    job_id: str,
    item_id: str,
    prompt: str,
    aplus: bool = False,
    instruction: str | None = None,
) -> None:
    session.add(ExecutionLog(
        job_id=None if aplus else job_id,
        aplus_job_id=job_id if aplus else None,
        item_id=None if aplus else item_id,
        node="image_model_prompt",
        status="prepared",
        request_summary=json.dumps({
            "item_id": item_id, "image_prompt": prompt, "instruction": instruction,
        }, ensure_ascii=False),
        dry_run=False,
    ))
    session.commit()
