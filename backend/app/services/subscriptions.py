from __future__ import annotations

import json
from uuid import uuid4
from datetime import timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.models import (
    PaymentOrder,
    PlanPrice,
    PlanQuotaRule,
    QuotaLedger,
    SubscriptionPlan,
    User,
    UserSubscription,
    utcnow,
)
from backend.app.services.notifications import create_notification


QUOTA_ACTIONS = [
    ("image_generation", "商品套图", "张"),
    ("aplus_generation", "A+ 详情", "张"),
    ("video_generation", "视频生成", "条"),
    ("edit_generation", "二次编辑", "次"),
    ("batch_suite", "批量套图", "个商品"),
    ("batch_aplus", "批量 A+", "个商品"),
]


DEFAULT_PLANS: list[dict[str, Any]] = [
    {
        "code": "free",
        "name": "免费版",
        "description": "适合先体验 Listingo 的基础内容生产流程。",
        "badge": "",
        "cta": "当前可用",
        "visible": True,
        "is_internal": False,
        "is_enterprise": False,
        "sort_order": 10,
        "features": ["免费体验商品套图", "少量 A+ 详情生成", "基础二次编辑", "历史任务保留 7 天"],
        "prices": [
            ("monthly", 0, "¥0", "/月"),
            ("yearly", 0, "¥0", "/年"),
        ],
        "quotas": {
            "image_generation": 20,
            "aplus_generation": 4,
            "video_generation": 2,
            "edit_generation": 10,
            "batch_suite": 2,
            "batch_aplus": 1,
        },
    },
    {
        "code": "standard",
        "name": "标准会员",
        "description": "适合稳定上新的个人卖家和小型电商团队。",
        "badge": "VIP",
        "cta": "立即订阅",
        "visible": True,
        "is_internal": False,
        "is_enterprise": False,
        "sort_order": 20,
        "features": ["包含免费版所有权益", "个人商业授权", "付费模板/素材", "智能抠图、消除与变清晰", "每月赠送生成额度"],
        "prices": [
            ("monthly", 3000, "¥30.0", "/月"),
            ("yearly", 30000, "¥300.0", "/年"),
        ],
        "quotas": {
            "image_generation": 330,
            "aplus_generation": 60,
            "video_generation": 12,
            "edit_generation": 160,
            "batch_suite": 20,
            "batch_aplus": 8,
        },
    },
    {
        "code": "advanced",
        "name": "高级会员",
        "description": "适合高频 SKU、批量上新和多平台内容生产。",
        "badge": "PRO",
        "cta": "立即订阅",
        "visible": True,
        "is_internal": False,
        "is_enterprise": False,
        "sort_order": 30,
        "features": ["包含标准会员所有权益", "更高月度额度", "批量任务优先", "大图与视频生产支持", "额度告急提醒"],
        "prices": [
            ("monthly", 8800, "¥88.0", "/月"),
            ("yearly", 88000, "¥880.0", "/年"),
        ],
        "quotas": {
            "image_generation": 1000,
            "aplus_generation": 240,
            "video_generation": 60,
            "edit_generation": 520,
            "batch_suite": 80,
            "batch_aplus": 30,
        },
    },
    {
        "code": "enterprise",
        "name": "企业定制版",
        "description": "面向团队协作、私有化部署和定制化开发需求。",
        "badge": "TEAM",
        "cta": "联系我们",
        "visible": True,
        "is_internal": False,
        "is_enterprise": True,
        "sort_order": 40,
        "features": ["企业商业授权", "团队账号与额度共享", "品牌导航与工作流定制", "SSO / 私有化部署方案", "专属支持与定制化开发"],
        "contact_text": "联系商务获取企业定制方案，可支持团队账号、品牌模板、私有化部署、定制化开发和专属额度配置。",
        "contact_phone": "18928268686",
        "prices": [
            ("monthly", None, "让我们聊聊", ""),
            ("yearly", None, "让我们聊聊", ""),
        ],
        "quotas": {
            "image_generation": 20000,
            "aplus_generation": 3000,
            "video_generation": 800,
            "edit_generation": 10000,
            "batch_suite": 1000,
            "batch_aplus": 500,
        },
    },
    {
        "code": "internal",
        "name": "Internal",
        "description": "管理员和内部测试账号使用，不在普通用户套餐页展示。",
        "badge": "ADMIN",
        "cta": "管理员配置",
        "visible": False,
        "is_internal": True,
        "is_enterprise": False,
        "sort_order": 99,
        "features": ["不限额度", "后台测试任务隔离", "用户与套餐管理", "审计日志", "生产配置检查"],
        "prices": [
            ("monthly", None, "内部", ""),
            ("yearly", None, "内部", ""),
        ],
        "quotas": {key: None for key, _, _ in QUOTA_ACTIONS},
    },
]


def _json_list(raw: str) -> list[str]:
    try:
        parsed = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def seed_subscription_defaults(session: Session) -> None:
    for index, preset in enumerate(DEFAULT_PLANS):
        plan = session.scalar(select(SubscriptionPlan).where(SubscriptionPlan.code == preset["code"]))
        if not plan:
            plan = SubscriptionPlan(code=preset["code"], name=preset["name"])
            session.add(plan)
            session.flush()
        plan.name = preset["name"]
        plan.description = preset["description"]
        plan.badge = preset.get("badge", "")
        plan.cta = preset.get("cta", "")
        plan.enabled = True
        plan.visible = bool(preset["visible"])
        plan.is_internal = bool(preset["is_internal"])
        plan.is_enterprise = bool(preset["is_enterprise"])
        plan.sort_order = int(preset.get("sort_order", index * 10))
        plan.features_json = json.dumps(preset["features"], ensure_ascii=False)
        plan.contact_text = preset.get("contact_text", "")
        plan.contact_phone = preset.get("contact_phone", "")

        existing_prices = {
            price.billing_cycle: price
            for price in session.scalars(select(PlanPrice).where(PlanPrice.plan_id == plan.id)).all()
        }
        for price_index, (cycle, amount, label, period) in enumerate(preset["prices"]):
            price = existing_prices.get(cycle)
            if not price:
                price = PlanPrice(plan_id=plan.id, billing_cycle=cycle)
                session.add(price)
            price.amount_cents = amount
            price.price_label = label
            price.period_label = period
            price.sort_order = price_index

        existing_rules = {
            rule.action_key: rule
            for rule in session.scalars(select(PlanQuotaRule).where(PlanQuotaRule.plan_id == plan.id)).all()
        }
        for action_key, action_label, unit in QUOTA_ACTIONS:
            rule = existing_rules.get(action_key)
            if not rule:
                rule = PlanQuotaRule(plan_id=plan.id, action_key=action_key, action_label=action_label)
                session.add(rule)
            rule.action_label = action_label
            rule.unit = unit
            rule.monthly_limit = preset["quotas"][action_key]
            rule.cost_multiplier = 1
            rule.warning_threshold = 80
            rule.enabled = True


def plan_by_code(session: Session, code: str) -> SubscriptionPlan | None:
    return session.scalar(select(SubscriptionPlan).where(SubscriptionPlan.code == code).limit(1))


def user_plan(session: Session, user: User) -> SubscriptionPlan:
    plan = plan_by_code(session, user.current_plan_code)
    if plan:
        return plan
    fallback = plan_by_code(session, "free")
    if not fallback:
        seed_subscription_defaults(session)
        fallback = plan_by_code(session, "free")
    user.current_plan_code = "free"
    return fallback


def serialize_plan(session: Session, plan: SubscriptionPlan, *, include_internal: bool = False) -> dict[str, Any]:
    prices = session.scalars(select(PlanPrice).where(PlanPrice.plan_id == plan.id).order_by(PlanPrice.sort_order)).all()
    rules = session.scalars(select(PlanQuotaRule).where(PlanQuotaRule.plan_id == plan.id).order_by(PlanQuotaRule.action_key)).all()
    return {
        "id": plan.id,
        "code": plan.code,
        "name": plan.name,
        "description": plan.description,
        "badge": plan.badge,
        "cta": plan.cta,
        "enabled": plan.enabled,
        "visible": plan.visible,
        "is_internal": plan.is_internal,
        "is_enterprise": plan.is_enterprise,
        "features": _json_list(plan.features_json),
        "contact_text": plan.contact_text,
        "contact_phone": plan.contact_phone,
        "prices": [
            {
                "id": price.id,
                "billing_cycle": price.billing_cycle,
                "amount_cents": price.amount_cents,
                "currency": price.currency,
                "price_label": price.price_label,
                "period_label": price.period_label,
            }
            for price in prices
        ],
        "quota_rules": [serialize_quota_rule(rule) for rule in rules],
        "sort_order": plan.sort_order,
    }


def serialize_quota_rule(rule: PlanQuotaRule) -> dict[str, Any]:
    return {
        "id": rule.id,
        "action_key": rule.action_key,
        "action_label": rule.action_label,
        "unit": rule.unit,
        "monthly_limit": rule.monthly_limit,
        "cost_multiplier": rule.cost_multiplier,
        "warning_threshold": rule.warning_threshold,
        "enabled": rule.enabled,
    }


def list_subscription_plans(session: Session, *, include_internal: bool = False) -> list[dict[str, Any]]:
    conditions = [SubscriptionPlan.enabled.is_(True)]
    if not include_internal:
        conditions.extend([SubscriptionPlan.visible.is_(True), SubscriptionPlan.is_internal.is_(False)])
    plans = session.scalars(select(SubscriptionPlan).where(*conditions).order_by(SubscriptionPlan.sort_order)).all()
    return [serialize_plan(session, plan, include_internal=include_internal) for plan in plans]


def quota_period() -> str:
    return utcnow().strftime("%Y-%m")


def quota_used(session: Session, user_id: str, action_key: str, period: str | None = None) -> int:
    period = period or quota_period()
    return session.scalar(
        select(func.coalesce(func.sum(QuotaLedger.amount), 0)).where(
            QuotaLedger.user_id == user_id,
            QuotaLedger.action_key == action_key,
            QuotaLedger.period == period,
            QuotaLedger.status.in_(["reserved", "confirmed"]),
        )
    ) or 0


def current_quota_summary(session: Session, user: User) -> dict[str, Any]:
    plan = user_plan(session, user)
    rules = session.scalars(select(PlanQuotaRule).where(PlanQuotaRule.plan_id == plan.id, PlanQuotaRule.enabled.is_(True))).all()
    period = quota_period()
    rows = []
    for rule in rules:
        used = 0 if rule.monthly_limit is None else quota_used(session, user.id, rule.action_key, period)
        rows.append(
            {
                **serialize_quota_rule(rule),
                "used": used,
                "remaining": None if rule.monthly_limit is None else max(0, rule.monthly_limit - used),
                "period": period,
            }
        )
    return {"plan": serialize_plan(session, plan), "period": period, "rows": rows}


def reserve_quota(
    session: Session,
    user: User,
    *,
    action_key: str,
    amount: int,
    ref_type: str,
    ref_id: str,
    description: str = "",
) -> QuotaLedger | None:
    if amount <= 0:
        return None
    plan = user_plan(session, user)
    if plan.is_internal:
        return None
    rule = session.scalar(
        select(PlanQuotaRule).where(
            PlanQuotaRule.plan_id == plan.id,
            PlanQuotaRule.action_key == action_key,
            PlanQuotaRule.enabled.is_(True),
        )
    )
    if not rule:
        raise HTTPException(status_code=402, detail="当前套餐未开放该能力")
    cost = amount * max(1, rule.cost_multiplier)
    period = quota_period()
    if rule.monthly_limit is not None:
        used = quota_used(session, user.id, action_key, period)
        if used + cost > rule.monthly_limit:
            raise HTTPException(
                status_code=402,
                detail=f"{rule.action_label}额度不足：剩余 {max(0, rule.monthly_limit - used)} {rule.unit}",
            )
    ledger = QuotaLedger(
        user_id=user.id,
        action_key=action_key,
        amount=cost,
        status="reserved",
        ref_type=ref_type,
        ref_id=ref_id,
        period=period,
        description=description,
    )
    session.add(ledger)
    session.flush()
    if rule.monthly_limit is not None:
        used_after = quota_used(session, user.id, action_key, period)
        threshold = max(0, min(100, rule.warning_threshold))
        if rule.monthly_limit > 0 and used_after * 100 >= rule.monthly_limit * threshold:
            create_notification(
                session,
                user.id,
                title="额度告急提醒",
                body=f"{rule.action_label} 本月额度已使用 {used_after}/{rule.monthly_limit} {rule.unit}，请及时调整套餐或联系管理员。",
                category="quota",
                metadata={"action_key": action_key, "period": period},
            )
    return ledger


def confirm_quota(session: Session, *, ref_type: str, ref_id: str) -> None:
    ledgers = session.scalars(
        select(QuotaLedger).where(QuotaLedger.ref_type == ref_type, QuotaLedger.ref_id == ref_id, QuotaLedger.status == "reserved")
    ).all()
    for ledger in ledgers:
        ledger.status = "confirmed"
        ledger.confirmed_at = utcnow()


def release_quota(session: Session, *, ref_type: str, ref_id: str) -> None:
    ledgers = session.scalars(
        select(QuotaLedger).where(QuotaLedger.ref_type == ref_type, QuotaLedger.ref_id == ref_id, QuotaLedger.status == "reserved")
    ).all()
    for ledger in ledgers:
        ledger.status = "released"
        ledger.released_at = utcnow()


def _price_for_cycle(session: Session, plan: SubscriptionPlan, billing_cycle: str) -> PlanPrice | None:
    return session.scalar(
        select(PlanPrice).where(PlanPrice.plan_id == plan.id, PlanPrice.billing_cycle == billing_cycle).limit(1)
    )


def create_payment_order(session: Session, user: User, *, plan_code: str, billing_cycle: str) -> PaymentOrder:
    plan = plan_by_code(session, plan_code)
    if not plan or not plan.enabled or plan.is_internal:
        raise HTTPException(status_code=404, detail="套餐不存在")
    price = _price_for_cycle(session, plan, billing_cycle)
    if not price:
        raise HTTPException(status_code=422, detail="该套餐不支持所选周期")
    order = PaymentOrder(
        order_no=f"MOCK{utcnow().strftime('%Y%m%d%H%M%S')}{user.uid[-4:]}{uuid4().hex[:6].upper()}",
        user_id=user.id,
        plan_id=plan.id,
        billing_cycle=billing_cycle,
        amount_cents=price.amount_cents,
        currency=price.currency,
        status="contact_requested" if plan.is_enterprise else "pending",
        expires_at=utcnow() + timedelta(minutes=30),
        snapshot_json=json.dumps(serialize_plan(session, plan), ensure_ascii=False, default=str),
    )
    session.add(order)
    session.flush()
    if plan.is_enterprise:
        create_notification(
            session,
            user.id,
            title="企业定制咨询已提交",
            body=plan.contact_text or "我们已记录你的企业版咨询，请等待商务联系。",
            category="payment",
            metadata={"order_id": order.id, "plan_code": plan.code},
        )
    return order


def mock_pay_order(session: Session, user: User, order_id: str) -> PaymentOrder:
    order = session.get(PaymentOrder, order_id)
    if not order or order.user_id != user.id:
        raise HTTPException(status_code=404, detail="订单不存在")
    if order.status == "paid":
        return order
    plan = session.get(SubscriptionPlan, order.plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="套餐不存在")
    if plan.is_enterprise:
        raise HTTPException(status_code=409, detail="企业版需要商务确认后由管理员配置")
    order.status = "paid"
    order.paid_at = utcnow()
    duration = timedelta(days=365 if order.billing_cycle == "yearly" else 31)
    subscription = UserSubscription(
        user_id=user.id,
        plan_id=plan.id,
        billing_cycle=order.billing_cycle,
        status="active",
        starts_at=utcnow(),
        ends_at=utcnow() + duration,
        source_order_id=order.id,
    )
    user.current_plan_code = plan.code
    session.add(subscription)
    create_notification(
        session,
        user.id,
        title="订阅已生效",
        body=f"{plan.name} 已开通，{order.billing_cycle == 'yearly' and '年付' or '月付'}额度已更新。",
        category="payment",
        metadata={"order_id": order.id, "plan_code": plan.code},
    )
    return order


def serialize_order(session: Session, order: PaymentOrder) -> dict[str, Any]:
    plan = session.get(SubscriptionPlan, order.plan_id)
    return {
        "id": order.id,
        "order_no": order.order_no,
        "plan_code": plan.code if plan else "",
        "plan_name": plan.name if plan else "",
        "billing_cycle": order.billing_cycle,
        "amount_cents": order.amount_cents,
        "currency": order.currency,
        "status": order.status,
        "paid_at": order.paid_at,
        "expires_at": order.expires_at,
        "created_at": order.created_at,
    }
