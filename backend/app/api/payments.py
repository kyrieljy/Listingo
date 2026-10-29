from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from backend.app.database import get_session
from backend.app.models import User, utcnow
from backend.app.services.auth import get_current_user, require_admin
from backend.app.services.subscriptions import has_active_paid_subscription, serialize_order
from backend.app.services.wechat_pay import PaymentError, locked_order, settle_transaction

router = APIRouter(prefix="/api/v1", tags=["payments"])


def gateway(request: Request):
    client = getattr(request.app.state, "wechat_pay", None)
    if client is None:
        raise HTTPException(status_code=503, detail="微信支付尚未配置，请联系客服")
    return client


@router.post("/subscription/orders/{order_id}/wechat-native")
def native_payment(order_id: str, request: Request, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    client = gateway(request)
    order = locked_order(session, order_id, user.id)
    if order.status != "pending" or not order.expires_at or order.expires_at <= utcnow():
        raise HTTPException(status_code=409, detail="订单已关闭或过期，请重新下单")
    if order.product_type == "subscription" and has_active_paid_subscription(session, user):
        raise HTTPException(status_code=409, detail="当前付费套餐尚未到期")
    if not order.amount_cents or order.amount_cents <= 0 or order.currency != "CNY":
        raise HTTPException(status_code=422, detail="订单金额或币种无效")
    if not order.code_url:
        # Persist channel before contacting WeChat: recovery must query ambiguous network failures.
        order.payment_channel = "wechat_native"
        session.commit()
        order = locked_order(session, order_id, user.id)
        if order.status != "pending" or order.expires_at <= utcnow():
            raise HTTPException(status_code=409, detail="订单已关闭或过期")
        if order.product_type == "subscription" and has_active_paid_subscription(session, user):
            raise HTTPException(status_code=409, detail="当前付费套餐尚未到期")
        if not order.code_url:
            order.code_url = client.native(order)
    session.commit()
    return {"order_id": order.id, "code_url": order.code_url, "expires_at": order.expires_at}


@router.get("/subscription/orders/{order_id}")
def payment_status(order_id: str, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    # Polling reads local state; a background worker performs bounded authoritative queries.
    from backend.app.models import PaymentOrder
    order = session.get(PaymentOrder, order_id)
    if not order or order.user_id != user.id:
        raise HTTPException(status_code=404, detail="订单不存在")
    return serialize_order(session, order)


@router.post("/payments/wechat/notify")
async def payment_notification(request: Request):
    client = gateway(request)
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 65536:
            raise HTTPException(status_code=413, detail="通知过大")
    data = client.notification(request.headers, bytes(body))

    def commit_payment():
        with request.app.state.session_factory() as session:
            settle_transaction(session, client, data)
            session.commit()

    await run_in_threadpool(commit_payment)
    return Response(status_code=204)


class ManualRefundRecord(BaseModel):
    reference: str = Field(min_length=1, max_length=100)
    note: str = Field(min_length=1, max_length=2000)


@router.post("/admin/payment-orders/{order_id}/refund-record", dependencies=[Depends(require_admin)])
def record_manual_refund(order_id: str, payload: ManualRefundRecord, session: Session = Depends(get_session)):
    """Record a verified full refund made in merchant portal; no gateway refund is initiated."""
    from sqlalchemy import select
    from backend.app.models import BeanGrant, UserSubscription
    order = locked_order(session, order_id)
    if order.status == "refunded":
        return serialize_order(session, order)
    if order.status not in {"paid", "manual_review"} or not order.wechat_transaction_id:
        raise HTTPException(status_code=409, detail="此订单不能登记退款")
    subscription_ids = list(session.scalars(select(UserSubscription.id).where(UserSubscription.source_order_id == order.id)))
    for grant in session.scalars(select(BeanGrant).where(
        (BeanGrant.source_key == f"order:{order.id}") | (BeanGrant.source_id.in_(subscription_ids))
    ).with_for_update()):
        grant.remaining_beans = 0
        grant.expires_at = utcnow()
    for subscription in session.scalars(select(UserSubscription).where(UserSubscription.source_order_id == order.id)):
        subscription.status = "refunded"
        subscription.ends_at = utcnow()
    session.flush()
    from backend.app.services.subscriptions import user_plan
    user_plan(session, session.get(User, order.user_id))
    order.status, order.refund_reference, order.refund_note = "refunded", payload.reference, payload.note
    session.commit()
    return serialize_order(session, order)
