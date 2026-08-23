from __future__ import annotations

"""Realtime counters derived from committed analytics facts."""

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.runtime import RuntimeStateService, default_runtime
from backend.app.core.storage.keys import metric_daily_key
from backend.app.models import AnalyticsEvent


def _day(value: datetime | None = None) -> tuple[str, datetime, datetime]:
    moment = value or datetime.now(tz=None)
    if moment.tzinfo is not None:
        moment = moment.astimezone(tz=None).astimezone(moment.tzinfo)
    start = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.strftime("%Y%m%d"), start, start + timedelta(days=1)


def increment_analytics_event_counters(
    event: AnalyticsEvent,
    runtime: RuntimeStateService | None = None,
) -> None:
    service = runtime or default_runtime()
    if service is None:
        return
    day, _, _ = _day(event.created_at)
    ttl = service.ttls.metric
    service.increment_best_effort(metric_daily_key(day, "total"), ttl)
    service.increment_best_effort(metric_daily_key(day, f"event_type:{event.event_type}"), ttl)
    if event.business_type:
        service.increment_best_effort(metric_daily_key(day, f"business_type:{event.business_type}"), ttl)


def realtime_metrics(
    session: Session,
    runtime: RuntimeStateService | None = None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    service = runtime or default_runtime()
    day, start, end = _day(now)

    event_types = session.scalars(
        select(AnalyticsEvent.event_type)
        .where(AnalyticsEvent.created_at >= start, AnalyticsEvent.created_at < end)
        .distinct()
    ).all()
    business_types = session.scalars(
        select(AnalyticsEvent.business_type)
        .where(AnalyticsEvent.business_type != "", AnalyticsEvent.created_at >= start, AnalyticsEvent.created_at < end)
        .distinct()
    ).all()

    def counter(name: str) -> int:
        if service is None:
            return 0
        value = service.get_json_best_effort(metric_daily_key(day, name))
        try:
            return max(0, int(value or 0))
        except (TypeError, ValueError):
            return 0

    return {
        "date": start.date().isoformat(),
        "total": counter("total"),
        "by_event_type": {key: counter(f"event_type:{key}") for key in sorted(event_types)},
        "by_business_type": {key: counter(f"business_type:{key}") for key in sorted(business_types)},
    }
