from __future__ import annotations

import json
from uuid import uuid5, NAMESPACE_URL
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import Notification, User, utcnow


def create_notification(
    session: Session,
    user_id: str,
    *,
    title: str,
    body: str,
    category: str = "system",
    metadata: dict[str, Any] | None = None,
) -> Notification:
    notification = Notification(
        user_id=user_id,
        category=category,
        title=title,
        body=body,
        unread=True,
        metadata_json=json.dumps(metadata or {}, ensure_ascii=False),
    )
    session.add(notification)
    return notification


def create_job_result_notification_once(
    session: Session,
    user_id: str,
    *,
    category: str,
    job_id: str,
    status: str,
    dry_run: bool,
) -> Notification:
    """Create one deterministic notification per terminal generation job."""
    notification_id = str(uuid5(NAMESPACE_URL, f"listingo:{category}:{job_id}"))
    existing = session.get(Notification, notification_id)
    if existing:
        return existing

    domain_label = "生图" if category == "generation" else "视频"
    if status == "succeeded":
        title = f"{domain_label}任务已完成"
        body = f"你的{domain_label}任务已完成，可前往工作台查看结果。"
    elif status == "partial_failed":
        title = f"{domain_label}任务部分完成"
        body = f"你的{domain_label}任务部分生成失败，可在工作台重试失败项。"
    else:
        title = f"{domain_label}任务生成失败"
        body = f"你的{domain_label}任务生成失败，可在工作台查看失败原因。"

    notification = Notification(
        id=notification_id,
        user_id=user_id,
        category=category,
        title=title,
        body=body,
        unread=True,
        metadata_json=json.dumps(
            {"job_id": job_id, "status": status, "dry_run": dry_run},
            ensure_ascii=False,
        ),
    )
    session.add(notification)
    return notification


def create_batch_result_notification_once(
    session: Session,
    user_id: str,
    *,
    batch_id: str,
    business_type: str,
    status: str,
    completed_count: int,
    failed_count: int,
    total_count: int,
) -> Notification:
    """Create one deterministic notification per terminal batch parent job."""
    notification_id = str(uuid5(NAMESPACE_URL, f"listingo:batch:{batch_id}"))
    existing = session.get(Notification, notification_id)
    if existing:
        return existing

    domain_label = "A+详情批量" if business_type == "aplus" else "商品套图批量"
    if status == "succeeded":
        title = f"{domain_label}任务已完成"
        body = f"你的{domain_label}任务已全部完成，可前往批量记录查看结果。"
    elif status == "partial_failed":
        title = f"{domain_label}任务部分完成"
        body = f"你的{domain_label}任务有 {failed_count} 个商品失败，可在批量记录查看详情。"
    else:
        title = f"{domain_label}任务生成失败"
        body = f"你的{domain_label}任务生成失败，可在批量记录查看失败原因。"

    notification = Notification(
        id=notification_id,
        user_id=user_id,
        category="batch",
        title=title,
        body=body,
        unread=True,
        metadata_json=json.dumps(
            {
                "batch_job_id": batch_id,
                "business_type": business_type,
                "status": status,
                "completed_count": completed_count,
                "failed_count": failed_count,
                "total_count": total_count,
            },
            ensure_ascii=False,
        ),
    )
    session.add(notification)
    return notification


def serialize_notification(notification: Notification) -> dict[str, Any]:
    try:
        metadata = json.loads(notification.metadata_json or "{}")
    except json.JSONDecodeError:
        metadata = {}
    return {
        "id": notification.id,
        "category": notification.category,
        "title": notification.title,
        "body": notification.body,
        "unread": notification.unread,
        "metadata": metadata,
        "created_at": notification.created_at,
        "read_at": notification.read_at,
    }


def list_user_notifications(session: Session, user: User, *, limit: int = 50) -> list[dict[str, Any]]:
    notifications = session.scalars(
        select(Notification)
        .where(Notification.user_id == user.id)
        .order_by(Notification.created_at.desc())
        .limit(limit)
    ).all()
    return [serialize_notification(item) for item in notifications]


def mark_notification_read(session: Session, notification: Notification) -> Notification:
    notification.unread = False
    notification.read_at = utcnow()
    return notification


def unread_count(session: Session, user: User) -> int:
    return len(
        session.scalars(
            select(Notification.id).where(Notification.user_id == user.id, Notification.unread.is_(True))
        ).all()
    )
