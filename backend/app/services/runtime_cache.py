from __future__ import annotations

"""TTL-bounded read helpers for rarely changing configuration facts.

Only JSON-compatible identifiers are cached. PostgreSQL remains authoritative
and an unavailable Redis is treated as a miss rather than a request failure.
"""

from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.runtime import RuntimeStateService, default_runtime
from backend.app.models import Prompt, Workflow


def active_prompt_version_id(
    session: Session,
    code: str,
    runtime: RuntimeStateService | None = None,
) -> str | None:
    service = runtime or default_runtime()
    if service is None:
        prompt = session.scalar(select(Prompt).where(Prompt.code == code).limit(1))
        return prompt.active_version_id if prompt else None

    def produce() -> str | None:
        prompt = session.scalar(select(Prompt).where(Prompt.code == code).limit(1))
        return prompt.active_version_id if prompt else None

    return service.cached_versioned("prompt", code, produce)


def active_workflow_version_id(
    session: Session,
    code: str,
    runtime: RuntimeStateService | None = None,
) -> str | None:
    service = runtime or default_runtime()
    if service is None:
        workflow = session.scalar(select(Workflow).where(Workflow.code == code).limit(1))
        return workflow.active_version_id if workflow else None

    def produce() -> str | None:
        workflow = session.scalar(select(Workflow).where(Workflow.code == code).limit(1))
        return workflow.active_version_id if workflow else None

    return service.cached_versioned("workflow", code, produce)


def cached_subscription_payload(
    identifier: str,
    producer: Callable[[], Any],
    runtime: RuntimeStateService | None = None,
) -> Any:
    service = runtime or default_runtime()
    if service is None:
        return producer()
    return service.cached_versioned("subscription", identifier, producer)


def invalidate_prompt_cache(runtime: RuntimeStateService | None = None) -> None:
    service = runtime or default_runtime()
    if service is not None:
        service.invalidate_best_effort("prompt")


def invalidate_workflow_cache(runtime: RuntimeStateService | None = None) -> None:
    service = runtime or default_runtime()
    if service is not None:
        service.invalidate_best_effort("workflow")


def invalidate_subscription_cache(runtime: RuntimeStateService | None = None) -> None:
    service = runtime or default_runtime()
    if service is not None:
        service.invalidate_best_effort("subscription")
