from __future__ import annotations

import json
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
