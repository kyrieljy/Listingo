from __future__ import annotations

import json
import logging
from uuid import uuid5, NAMESPACE_URL
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.config import Settings
from backend.app.models import Notification, User, utcnow
from backend.app.security import ApiKeyCipher


logger = logging.getLogger(__name__)


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


def build_task_result_title(*, category: str, business_type: str | None = None, status: str) -> str:
    """Single source of truth for task-completion notice text across all channels.

    Used by the in-app notification, the SMS notify template and the Feishu
    webhook so the three channels can never drift apart.
    """
    if category == "batch":
        domain_label = "A+详情批量" if business_type == "aplus" else "商品套图批量"
    else:
        domain_label = "生图" if category == "generation" else "视频"
    if status == "succeeded":
        return f"{domain_label}任务已完成"
    if status == "partial_failed":
        return f"{domain_label}任务部分完成"
    return f"{domain_label}任务生成失败"


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

    title = build_task_result_title(category=category, status=status)
    domain_label = "生图" if category == "generation" else "视频"
    if status == "succeeded":
        body = f"你的{domain_label}任务已完成，可前往工作台查看结果。"
    elif status == "partial_failed":
        body = f"你的{domain_label}任务部分生成失败，可在工作台重试失败项。"
    else:
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
    title = build_task_result_title(category="batch", business_type=business_type, status=status)
    if status == "succeeded":
        body = f"你的{domain_label}任务已全部完成，可前往批量记录查看结果。"
    elif status == "partial_failed":
        body = f"你的{domain_label}任务有 {failed_count} 个商品失败，可在批量记录查看详情。"
    else:
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


FEISHU_TEST_TEXT = "设计就上Listingo"


class FeishuWebhookError(RuntimeError):
    """Feishu webhook POST failed; `args[0]` is a user-facing Chinese reason."""


async def _post_feishu_webhook(url: str, text: str, *, timeout: float) -> None:
    """POST a plain-text message to a user-configured Feishu custom-bot webhook.

    Raises FeishuWebhookError on transport failures, HTTP errors and Feishu's own
    `code != 0` payloads — the latter arrive with HTTP 200, so raise_for_status()
    alone would silently treat them as success. Callers that must never fail (the
    worker notify path) log and swallow the error.
    """
    payload = {"msg_type": "text", "content": {"text": text}}
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
    except httpx.TimeoutException:
        raise FeishuWebhookError("推送超时，请检查 Webhook 地址是否正确") from None
    except httpx.HTTPStatusError as exc:
        raise FeishuWebhookError(f"推送失败（HTTP {exc.response.status_code}）") from exc
    except httpx.RequestError as exc:
        raise FeishuWebhookError(f"无法连接 Webhook 地址：{exc}") from exc

    json_method = getattr(response, "json", None)
    if json_method is None:
        return
    try:
        body = json_method()
    except ValueError:
        return
    if isinstance(body, dict) and body.get("code") not in (None, 0):
        raise FeishuWebhookError(f"飞书返回错误：{body.get('msg') or body.get('code')}")


async def send_feishu_webhook_test(url: str, *, timeout: float) -> None:
    """Push the fixed probe text to a Feishu webhook (user-facing test action)."""
    await _post_feishu_webhook(url, FEISHU_TEST_TEXT, timeout=timeout)


async def notify_task_completion_external(
    session: Session,
    settings: Settings,
    cipher: ApiKeyCipher,
    *,
    user: User,
    category: str,
    business_type: str | None = None,
    status: str,
    dry_run: bool = False,
) -> None:
    """Best-effort external notification (Feishu webhook + SMS) on task terminal.

    Failures are logged only and never raised, so a broken webhook or SMS channel
    can never affect the task terminal state or the worker loop. Called exactly once
    per terminal task from the real-time tick path; never from reconcile.
    """
    text = build_task_result_title(category=category, business_type=business_type, status=status)

    webhook = (user.feishu_webhook or "").strip()
    if webhook:
        try:
            await _post_feishu_webhook(webhook, text, timeout=settings.sms_timeout_seconds)
        except Exception:
            logger.warning("Feishu webhook notify failed for user %s", user.id, exc_info=True)

    try:
        # Lazy import avoids a circular dependency with sms.py.
        from backend.app.services.sms import send_sms_notification

        await send_sms_notification(session, settings, cipher, phone=user.phone, text=text)
    except Exception:
        logger.warning("SMS completion notify failed for user %s", user.id, exc_info=True)
