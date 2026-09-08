from __future__ import annotations

import json
import logging
from datetime import timedelta
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import event, func, or_, select
from sqlalchemy.orm import Session

from backend.app.core.runtime import RuntimeStateService, default_runtime
from backend.app.core.storage.base import StorageUnavailableError
from backend.app.core.storage.keys import lock_key
from backend.app.models import (
    BeanGrant,
    BeanLedger,
    BeanPack,
    CommercialBillingConfig,
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
from backend.app.services.runtime_cache import cached_subscription_payload


logger = logging.getLogger(__name__)
BEANS_PER_IMAGE = 12
INSUFFICIENT_BEANS_CODE = "INSUFFICIENT_BEANS"
LEGACY_PAID_PLAN_CODES = {"standard", "advanced", "enterprise"}
LEGACY_CONVERTIBLE_ACTIONS = ("image_generation", "aplus_generation", "edit_generation")


class RuntimeLockBusyError(RuntimeError):
    """Raised when another request owns a correctness lock."""


def _release_session_locks(session: Session, *_transaction_args: object) -> None:
    locks = session.info.pop("_listingo_runtime_locks", [])
    for key, token, service in locks:
        try:
            service.release_lock(key, token)
        except StorageUnavailableError:
            logger.warning("Runtime lock release failed; TTL will reclaim it", exc_info=True)


event.listen(Session, "after_commit", _release_session_locks)
event.listen(Session, "after_soft_rollback", _release_session_locks)


def _lock_for_session(
    session: Session,
    scope: str,
    identifier: str,
    runtime: RuntimeStateService | None = None,
) -> None:
    """Bind a token lock to the DB transaction so it survives until commit."""
    service = runtime or default_runtime()
    if service is None:
        return
    key = lock_key(scope, identifier)
    locks = session.info.setdefault("_listingo_runtime_locks", [])
    if any(existing_key == key for existing_key, _, _ in locks):
        return
    token = service.acquire_lock(key, service.ttls.lock)
    if token is None:
        raise RuntimeLockBusyError(f"Operation is already in progress: {scope}")
    locks.append((key, token, service))


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
        "description": "未开通会员时可使用已购买的豆子生成图片。",
        "badge": "",
        "cta": "购买豆子",
        "visible": False,
        "is_internal": False,
        "is_enterprise": False,
        "sort_order": 0,
        "features": ["自购豆子生成高清图片", "低清预览免费", "图片编辑与重绘"],
        "prices": [],
        "billing_cycle": "none",
        "beans": 0,
        "recommended": False,
        "contact_sales": False,
        "entitlements": {"image_generation": True, "image_edit": True, "batch_generation": False},
    },
    {
        "code": "monthly_basic",
        "name": "轻量版",
        "description": "适合刚开始尝试 AI 商品图的个人卖家，满足少量商品上新需求。",
        "badge": "",
        "cta": "立即订阅",
        "sort_order": 10,
        "features": ["480 豆/月", "高清图片生成", "图片编辑 / 重绘"],
        "prices": [("monthly", 4900, "¥49", "/月")],
        "billing_cycle": "monthly",
        "beans": 480,
        "recommended": False,
        "contact_sales": False,
        "entitlements": {"image_generation": True, "image_edit": True, "batch_generation": False, "priority_queue": False, "team_collaboration": False},
    },
    {
        "code": "monthly_standard",
        "name": "标准版",
        "description": "适合稳定上新的电商卖家，支持商品图、详情图和图片编辑。",
        "badge": "推荐",
        "cta": "立即订阅",
        "sort_order": 20,
        "features": ["1560 豆/月", "基础批量生成", "图片编辑 / 重绘"],
        "prices": [("monthly", 12900, "¥129", "/月")],
        "billing_cycle": "monthly",
        "beans": 1560,
        "recommended": True,
        "contact_sales": False,
        "entitlements": {"image_generation": True, "image_edit": True, "batch_generation": True, "priority_queue": "basic", "team_collaboration": False},
    },
    {
        "code": "monthly_pro",
        "name": "高级版",
        "description": "适合多 SKU 上新、批量商品图生产和小团队协作。",
        "badge": "",
        "cta": "立即订阅",
        "sort_order": 30,
        "features": ["9600 豆/月", "批量生成", "基础团队协作"],
        "prices": [("monthly", 69900, "¥699", "/月")],
        "billing_cycle": "monthly",
        "beans": 9600,
        "recommended": False,
        "contact_sales": False,
        "entitlements": {"image_generation": True, "image_edit": True, "batch_generation": True, "priority_queue": True, "team_collaboration": "basic"},
    },
    {
        "code": "yearly_basic",
        "name": "轻量年付",
        "description": "适合少量商品上新，全年豆子可用于商品图、详情图和图片编辑。",
        "badge": "年付更省",
        "cta": "立即订阅",
        "sort_order": 40,
        "features": ["5760 豆/年", "批量生成", "高清图片与图片编辑"],
        "prices": [("yearly", 49900, "¥499", "/年")],
        "billing_cycle": "yearly",
        "beans": 5760,
        "recommended": False,
        "contact_sales": False,
        "entitlements": {"image_generation": True, "image_edit": True, "batch_generation": True, "priority_queue": True, "team_collaboration": False},
    },
    {
        "code": "yearly_standard",
        "name": "标准年付",
        "description": "适合持续上新的卖家，全年更划算，支持批量上传和批量生成。",
        "badge": "推荐",
        "cta": "立即订阅",
        "sort_order": 50,
        "features": ["18000 豆/年", "批量生成", "高清图片与图片编辑"],
        "prices": [("yearly", 129900, "¥1299", "/年")],
        "billing_cycle": "yearly",
        "beans": 18000,
        "recommended": True,
        "contact_sales": False,
        "entitlements": {"image_generation": True, "image_edit": True, "batch_generation": True, "priority_queue": True, "team_collaboration": False},
    },
    {
        "code": "yearly_flagship",
        "name": "旗舰年付",
        "description": "适合团队批量生产电商内容，支持大额豆子、批量任务和团队协作。",
        "badge": "团队首选",
        "cta": "立即订阅",
        "sort_order": 60,
        "features": ["288000 豆/年", "高级批量生成", "团队协作与专属客服"],
        "prices": [("yearly", 1999900, "¥19999", "/年")],
        "billing_cycle": "yearly",
        "beans": 288000,
        "recommended": False,
        "contact_sales": False,
        "entitlements": {
            "image_generation": True,
            "image_edit": True,
            "batch_generation": "advanced",
            "priority_queue": True,
            "team_collaboration": True,
            "exclusive_support": True,
            "api_access": False,
        },
    },
    {
        "code": "enterprise_custom",
        "name": "企业定制版",
        "description": "面向品牌方、代运营团队和批量内容生产团队，根据用量与需求定制方案。",
        "badge": "企业定制",
        "cta": "联系我们",
        "sort_order": 70,
        "features": ["团队协作", "API 接入可沟通", "定制工作流", "专属客服"],
        "prices": [],
        "billing_cycle": "custom",
        "beans": None,
        "recommended": False,
        "contact_sales": True,
        "entitlements": {
            "image_generation": True,
            "image_edit": True,
            "batch_generation": "custom",
            "priority_queue": True,
            "team_collaboration": True,
            "api_access": "negotiable",
            "custom_workflow": True,
            "exclusive_support": True,
        },
        "contact_text": "企业版不展示固定价格，请联系商务获取专属报价。",
        "contact_phone": "18928268686",
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
        "features": ["不限豆子", "后台测试任务隔离", "用户与套餐管理", "审计日志"],
        "prices": [],
        "billing_cycle": "internal",
        "beans": None,
        "recommended": False,
        "contact_sales": False,
        "entitlements": {"image_generation": True, "image_edit": True, "batch_generation": True, "priority_queue": True, "team_collaboration": True},
    },
]

OLD_COMMERCIAL_PLAN_CODES = ("standard", "advanced", "enterprise")

DEFAULT_BEAN_PACKS = [
    ("beans_50", "临时补豆包", 5000, 360, False, 10),
    ("beans_129", "常用补豆包", 12900, 960, False, 20),
    ("beans_399", "高频补豆包", 39900, 3120, True, 30),
    ("beans_999", "团队补豆包", 99900, 8400, False, 40),
]


def _json_list(raw: str) -> list[str]:
    try:
        parsed = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def _json_dict(raw: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _seed_plan(session: Session, preset: dict[str, Any]) -> SubscriptionPlan:
    plan = session.scalar(select(SubscriptionPlan).where(SubscriptionPlan.code == preset["code"]).limit(1))
    created = plan is None
    # free/internal are fixed system fallbacks; stale pre-V1 metadata must not
    # turn them into a commercial entitlement source after an in-place upgrade.
    if created:
        plan = SubscriptionPlan(code=preset["code"], name=preset["name"])
        session.add(plan)
        session.flush()
    if created or plan.code in {"free", "internal"}:
        plan.name = preset["name"]
        plan.description = preset["description"]
        plan.badge = preset.get("badge", "")
        plan.cta = preset.get("cta", "")
        plan.visible = bool(preset.get("visible", True))
        plan.is_internal = bool(preset.get("is_internal", False))
        plan.is_enterprise = bool(preset.get("is_enterprise", False))
        plan.billing_cycle = preset["billing_cycle"]
        plan.beans = preset["beans"]
        plan.recommended = bool(preset["recommended"])
        plan.contact_sales = bool(preset["contact_sales"])
        plan.sort_order = int(preset["sort_order"])
        plan.features_json = json.dumps(preset["features"], ensure_ascii=False)
        plan.entitlements_json = json.dumps(preset["entitlements"], ensure_ascii=False)
        plan.contact_text = preset.get("contact_text", "")
        plan.contact_phone = preset.get("contact_phone", "")
    plan.enabled = plan.code == "internal" or plan.code not in OLD_COMMERCIAL_PLAN_CODES
    if plan.code in OLD_COMMERCIAL_PLAN_CODES:
        plan.visible = False

    expected_cycles = {price[0] for price in preset["prices"]}
    existing_prices = list(session.scalars(select(PlanPrice).where(PlanPrice.plan_id == plan.id)).all())
    existing_by_cycle = {price.billing_cycle: price for price in existing_prices}
    for price_index, (cycle, amount, label, period) in enumerate(preset["prices"]):
        price = existing_by_cycle.get(cycle)
        if not price and created:
            price = PlanPrice(
                plan_id=plan.id,
                billing_cycle=cycle,
                amount_cents=amount,
                currency="CNY",
                price_label=label,
                period_label=period,
                sort_order=price_index,
            )
            session.add(price)
    return plan


def seed_subscription_defaults(session: Session) -> None:
    """Create the V1 catalog once while retaining editable administrator values."""
    for preset in DEFAULT_PLANS:
        _seed_plan(session, preset)

    for action_key, action_label, unit in QUOTA_ACTIONS:
        rules = session.scalars(select(PlanQuotaRule).where(PlanQuotaRule.action_key == action_key)).all()
        for rule in rules:
            rule.action_label = action_label
            rule.unit = unit

    for code, name, amount_cents, beans, recommended, sort_order in DEFAULT_BEAN_PACKS:
        if not session.scalar(select(BeanPack).where(BeanPack.code == code).limit(1)):
            session.add(
                BeanPack(
                    code=code,
                    name=name,
                    amount_cents=amount_cents,
                    beans=beans,
                    recommended=recommended,
                    sort_order=sort_order,
                )
            )

    if not session.scalar(select(CommercialBillingConfig).limit(1)):
        session.add(CommercialBillingConfig())

    session.flush()
    migrate_legacy_quotas(session)


def plan_by_code(session: Session, code: str) -> SubscriptionPlan | None:
    return session.scalar(select(SubscriptionPlan).where(SubscriptionPlan.code == code).limit(1))


def active_subscription(session: Session, user: User) -> UserSubscription | None:
    now = utcnow()
    return session.scalar(
        select(UserSubscription)
        .join(SubscriptionPlan, SubscriptionPlan.id == UserSubscription.plan_id)
        .where(
            UserSubscription.user_id == user.id,
            UserSubscription.status == "active",
            UserSubscription.starts_at <= now,
            or_(UserSubscription.ends_at.is_(None), UserSubscription.ends_at > now),
            SubscriptionPlan.enabled.is_(True),
            ~SubscriptionPlan.code.in_(OLD_COMMERCIAL_PLAN_CODES),
        )
        .order_by(UserSubscription.starts_at.desc(), UserSubscription.created_at.desc())
        .limit(1)
    )


def user_plan(session: Session, user: User) -> SubscriptionPlan:
    subscription = active_subscription(session, user)
    if subscription:
        plan = session.get(SubscriptionPlan, subscription.plan_id)
        if plan:
            user.current_plan_code = plan.code
            return plan
    if user.role == "admin":
        internal = plan_by_code(session, "internal")
        if internal:
            user.current_plan_code = internal.code
            return internal
    if user.current_plan_code == "internal":
        internal = plan_by_code(session, "internal")
        if internal:
            return internal
    fallback = plan_by_code(session, "free")
    if not fallback:
        seed_subscription_defaults(session)
        fallback = plan_by_code(session, "free")
    user.current_plan_code = fallback.code
    return fallback


def plan_entitlement(session: Session, user: User, key: str) -> Any:
    plan = user_plan(session, user)
    if plan.is_internal:
        return True
    return bool(_json_dict(plan.entitlements_json).get(key, False))


def serialize_plan(session: Session, plan: SubscriptionPlan, *, include_internal: bool = False) -> dict[str, Any]:
    def produce() -> dict[str, Any]:
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
            "billing_cycle": plan.billing_cycle,
            "beans": plan.beans,
            "recommended": plan.recommended,
            "contact_sales": plan.contact_sales,
            "features": _json_list(plan.features_json),
            "entitlements": _json_dict(plan.entitlements_json),
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

    return cached_subscription_payload(f"plan:{plan.id}", produce)


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


def list_bean_packs(session: Session) -> list[dict[str, Any]]:
    def produce() -> list[dict[str, Any]]:
        packs = session.scalars(
            select(BeanPack).where(BeanPack.enabled.is_(True), BeanPack.visible.is_(True)).order_by(BeanPack.sort_order)
        ).all()
        return [
            {
                "id": pack.id,
                "code": pack.code,
                "name": pack.name,
                "description": pack.description,
                "amount_cents": pack.amount_cents,
                "currency": pack.currency,
                "beans": pack.beans,
                "recommended": pack.recommended,
                "enabled": pack.enabled,
                "visible": pack.visible,
                "sort_order": pack.sort_order,
            }
            for pack in packs
        ]

    return cached_subscription_payload("bean-packs:public", produce)


def billing_settings(session: Session) -> CommercialBillingConfig:
    settings = session.scalar(select(CommercialBillingConfig).limit(1))
    if not settings:
        settings = CommercialBillingConfig()
        session.add(settings)
        session.flush()
    return settings


def video_feature_enabled(session: Session) -> bool:
    return billing_settings(session).video_enabled


def _available_grants(session: Session, user_id: str, *, for_update: bool = False) -> list[BeanGrant]:
    now = utcnow()
    query = (
        select(BeanGrant)
        .where(
            BeanGrant.user_id == user_id,
            BeanGrant.remaining_beans > 0,
            or_(BeanGrant.expires_at.is_(None), BeanGrant.expires_at > now),
        )
        .order_by(BeanGrant.expires_at.nulls_last(), BeanGrant.created_at)
    )
    if for_update:
        query = query.with_for_update()
    return list(session.scalars(query).all())


def available_beans(session: Session, user_id: str) -> int:
    session.flush()
    grants = _available_grants(session, user_id)
    return sum(grant.remaining_beans for grant in grants)


def assert_beans_sufficient(session: Session, user: User, required: int) -> None:
    """非计费任务的余额充足性预检：只校验、不写 BeanLedger、不预留。

    用于 A+ plan / 文案辅助等本身不产生计费的辅助入口——此类任务不扣豆，
    但仍需在执行前拦截余额不足的用户（required = 产出数量 × BEANS_PER_IMAGE）。
    该预检属本地校验，不随 dry_run 跳过。internal（含 admin）视为无限额度。
    """
    if required <= 0:
        return
    plan = user_plan(session, user)
    if plan.is_internal:
        return
    available = available_beans(session, user.id)
    if available < required:
        raise HTTPException(
            status_code=402,
            detail={
                "code": INSUFFICIENT_BEANS_CODE,
                "message": f"豆子不足：本次需要 {required} 豆，当前可用 {available} 豆。",
                "required_beans": required,
                "available_beans": available,
            },
        )


def reserved_beans(session: Session, user_id: str) -> int:
    session.flush()
    rows = session.scalars(
        select(BeanLedger).where(
            BeanLedger.user_id == user_id,
            BeanLedger.status.in_(["reserved", "partially_confirmed"]),
        )
    ).all()
    return sum(max(0, row.amount - row.confirmed_amount - row.released_amount) for row in rows)


def grant_beans(
    session: Session,
    user_id: str,
    *,
    amount: int,
    expires_at: Any,
    source_type: str,
    source_id: str | None,
    source_key: str,
    description: str = "",
) -> BeanGrant | None:
    if amount <= 0:
        return None
    existing = session.scalar(select(BeanGrant).where(BeanGrant.source_key == source_key).limit(1))
    if existing:
        return existing
    grant = BeanGrant(
        user_id=user_id,
        amount=amount,
        remaining_beans=amount,
        expires_at=expires_at,
        source_type=source_type,
        source_id=source_id,
        source_key=source_key,
        description=description,
    )
    session.add(grant)
    session.flush()
    return grant


def reserve_beans(
    session: Session,
    user: User,
    *,
    amount: int,
    ref_type: str,
    ref_id: str,
    description: str = "",
    refs: list[str] | None = None,
) -> BeanLedger | None:
    if amount <= 0:
        return None
    try:
        _lock_for_session(session, "beans", user.id)
    except RuntimeLockBusyError as exc:
        raise HTTPException(status_code=409, detail="豆子操作正在处理中，请稍后重试") from exc
    plan = user_plan(session, user)
    if plan.is_internal:
        return None
    session.flush()
    grants = _available_grants(session, user.id, for_update=True)
    available = sum(grant.remaining_beans for grant in grants)
    if available < amount:
        raise HTTPException(
            status_code=402,
            detail={
                "code": INSUFFICIENT_BEANS_CODE,
                "message": f"豆子不足：本次需要 {amount} 豆，当前可用 {available} 豆。",
                "required_beans": amount,
                "available_beans": available,
            },
        )

    remaining = amount
    cursor = 0
    allocations: list[dict[str, Any]] = []
    for grant in grants:
        taken = min(grant.remaining_beans, remaining)
        if taken <= 0:
            continue
        grant.remaining_beans -= taken
        allocations.append({"grant_id": grant.id, "amount": taken, "position": cursor})
        cursor += taken
        remaining -= taken
        if remaining == 0:
            break
    ledger = BeanLedger(
        user_id=user.id,
        ref_type=ref_type,
        ref_id=ref_id,
        amount=amount,
        status="reserved",
        description=description,
        refs_json=json.dumps(refs or [], ensure_ascii=False),
        allocations_json=json.dumps(allocations, ensure_ascii=False),
    )
    session.add(ledger)
    session.flush()
    return ledger


def _restore_allocations(session: Session, ledger: BeanLedger, amount: int) -> None:
    if amount <= 0:
        return
    remaining_restore = amount
    consumed_before = ledger.confirmed_amount + ledger.released_amount
    for allocation in _json_dict_list(ledger.allocations_json):
        if remaining_restore == 0:
            break
        position = int(allocation.get("position", 0))
        allocation_amount = int(allocation.get("amount", 0))
        untouched_start = max(position, consumed_before)
        restore = min(allocation_amount - (untouched_start - position), remaining_restore)
        if restore <= 0:
            continue
        grant = session.get(BeanGrant, str(allocation.get("grant_id")))
        if grant:
            grant.remaining_beans += restore
        remaining_restore -= restore


def _json_dict_list(raw: str) -> list[dict[str, Any]]:
    try:
        parsed = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _settle_ledger(
    session: Session,
    ledger: BeanLedger,
    *,
    confirm_amount: int,
    final_status: str,
) -> None:
    if ledger.status not in {"reserved", "partially_confirmed"}:
        return
    remaining = max(0, ledger.amount - ledger.confirmed_amount - ledger.released_amount)
    confirm_delta = min(max(0, confirm_amount), remaining)
    release_delta = remaining - confirm_delta
    ledger.confirmed_amount += confirm_delta
    _restore_allocations(session, ledger, release_delta)
    ledger.released_amount += release_delta
    ledger.status = final_status if confirm_delta == 0 else "settled"
    if confirm_delta:
        ledger.confirmed_at = ledger.confirmed_at or utcnow()
    if release_delta:
        ledger.released_at = ledger.released_at or utcnow()


def confirm_beans(
    session: Session,
    *,
    ref_type: str,
    ref_id: str,
    confirm_amount: int | None = None,
    ledger_id: str | None = None,
) -> None:
    conditions = [
            BeanLedger.ref_type == ref_type,
            BeanLedger.ref_id == ref_id,
            BeanLedger.status.in_(["reserved", "partially_confirmed"]),
    ]
    if ledger_id:
        conditions.append(BeanLedger.id == ledger_id)
    ledgers = session.scalars(select(BeanLedger).where(*conditions)).all()
    if confirm_amount is None:
        for ledger in ledgers:
            _settle_ledger(session, ledger, confirm_amount=ledger.amount - ledger.confirmed_amount - ledger.released_amount, final_status="confirmed")
        return
    left_to_confirm = max(0, confirm_amount)
    for ledger in ledgers:
        if left_to_confirm <= 0:
            _settle_ledger(session, ledger, confirm_amount=0, final_status="released")
            continue
        row_remaining = max(0, ledger.amount - ledger.confirmed_amount - ledger.released_amount)
        confirmed = min(row_remaining, left_to_confirm)
        left_to_confirm -= confirmed
        _settle_ledger(session, ledger, confirm_amount=confirmed, final_status="confirmed")


def release_beans(session: Session, *, ref_type: str, ref_id: str) -> None:
    ledgers = session.scalars(
        select(BeanLedger).where(
            BeanLedger.ref_type == ref_type,
            BeanLedger.ref_id == ref_id,
            BeanLedger.status.in_(["reserved", "partially_confirmed"]),
        )
    ).all()
    for ledger in ledgers:
        _settle_ledger(session, ledger, confirm_amount=0, final_status="released")


def refund_beans(session: Session, *, ref_type: str, ref_id: str) -> None:
    release_beans(session, ref_type=ref_type, ref_id=ref_id)


def bean_summary(session: Session, user: User) -> dict[str, Any]:
    plan = user_plan(session, user)
    subscription = active_subscription(session, user)
    available = None if plan.is_internal else available_beans(session, user.id)
    reserved = None if plan.is_internal else reserved_beans(session, user.id)
    expiring: list[dict[str, Any]] = []
    if not plan.is_internal:
        for grant in _available_grants(session, user.id):
            expiring.append(
                {
                    "id": grant.id,
                    "remaining_beans": grant.remaining_beans,
                    "expires_at": grant.expires_at,
                    "source_type": grant.source_type,
                }
            )
    return {
        "plan": serialize_plan(session, plan),
        "subscription_ends_at": subscription.ends_at if subscription else None,
        "beans_per_image": billing_settings(session).beans_per_image,
        "available_beans": available,
        "reserved_beans": reserved,
        "unlimited": plan.is_internal,
        "expiring_batches": expiring,
    }


def current_quota_summary(session: Session, user: User) -> dict[str, Any]:
    return bean_summary(session, user)


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


def _month_end(now: Any) -> Any:
    if now.month == 12:
        return now.replace(year=now.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    return now.replace(month=now.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0)


def migrate_legacy_quotas(session: Session) -> None:
    """One-time B-plan conversion for still-active legacy paid subscriptions."""
    now = utcnow()
    period = quota_period()
    subscriptions = session.scalars(
        select(UserSubscription)
        .join(SubscriptionPlan, SubscriptionPlan.id == UserSubscription.plan_id)
        .where(
            UserSubscription.status == "active",
            UserSubscription.starts_at <= now,
            or_(UserSubscription.ends_at.is_(None), UserSubscription.ends_at > now),
            SubscriptionPlan.code.in_(LEGACY_PAID_PLAN_CODES),
        )
    ).all()
    by_user: dict[str, UserSubscription] = {}
    for subscription in subscriptions:
        current = by_user.get(subscription.user_id)
        if current is None or subscription.starts_at > current.starts_at:
            by_user[subscription.user_id] = subscription

    for user_id, subscription in by_user.items():
        source_key = f"legacy_quota_migration:{user_id}"
        if session.scalar(select(BeanGrant).where(BeanGrant.source_key == source_key).limit(1)):
            continue
        rules = session.scalars(select(PlanQuotaRule).where(PlanQuotaRule.plan_id == subscription.plan_id)).all()
        beans = 0
        for rule in rules:
            if rule.action_key not in LEGACY_CONVERTIBLE_ACTIONS or rule.monthly_limit is None:
                continue
            used = quota_used(session, user_id, rule.action_key, period)
            beans += max(0, int(rule.monthly_limit) - used) * BEANS_PER_IMAGE
        if beans > 0:
            grant_beans(
                session,
                user_id,
                amount=beans,
                expires_at=subscription.ends_at or _month_end(now),
                source_type="legacy_quota_migration",
                source_id=subscription.id,
                source_key=source_key,
                description="旧动作额度剩余量一次性折算",
            )


def _price_for_cycle(session: Session, plan: SubscriptionPlan, billing_cycle: str) -> PlanPrice | None:
    return session.scalar(
        select(PlanPrice).where(PlanPrice.plan_id == plan.id, PlanPrice.billing_cycle == billing_cycle).limit(1)
    )


def _order_no(user: User) -> str:
    return f"MOCK{utcnow().strftime('%Y%m%d%H%M%S')}{user.uid[-4:]}{uuid4().hex[:6].upper()}"


def create_payment_order(
    session: Session,
    user: User,
    *,
    plan_code: str | None = None,
    billing_cycle: str = "monthly",
    bean_pack_code: str | None = None,
) -> PaymentOrder:
    try:
        _lock_for_session(session, "order-create", user.id)
    except RuntimeLockBusyError as exc:
        raise HTTPException(status_code=409, detail="订单正在创建中，请稍后重试") from exc

    if bean_pack_code:
        pack = session.scalar(select(BeanPack).where(BeanPack.code == bean_pack_code, BeanPack.enabled.is_(True)).limit(1))
        if not pack:
            raise HTTPException(status_code=404, detail="补豆包不存在")
        order = PaymentOrder(
            order_no=_order_no(user),
            user_id=user.id,
            plan_id=None,
            billing_cycle="one_time",
            product_type="bean_pack",
            bean_pack_id=pack.id,
            amount_cents=pack.amount_cents,
            currency=pack.currency,
            status="pending",
            expires_at=utcnow() + timedelta(minutes=30),
            snapshot_json=json.dumps({"code": pack.code, "name": pack.name, "beans": pack.beans}, ensure_ascii=False),
        )
        session.add(order)
        session.flush()
        return order

    if not plan_code:
        raise HTTPException(status_code=422, detail="请选择要购买的商品")
    plan = plan_by_code(session, plan_code)
    if not plan or not plan.enabled or plan.is_internal:
        raise HTTPException(status_code=404, detail="套餐不存在")
    if plan.contact_sales:
        raise HTTPException(status_code=422, detail="企业定制版请提交商务咨询")
    cycle = plan.billing_cycle if plan.billing_cycle in {"monthly", "yearly"} else billing_cycle
    price = _price_for_cycle(session, plan, cycle)
    if not price:
        raise HTTPException(status_code=422, detail="该套餐不支持所选周期")
    order = PaymentOrder(
        order_no=_order_no(user),
        user_id=user.id,
        plan_id=plan.id,
        billing_cycle=cycle,
        product_type="subscription",
        amount_cents=price.amount_cents,
        currency=price.currency,
        status="pending",
        expires_at=utcnow() + timedelta(minutes=30),
        snapshot_json=json.dumps(serialize_plan(session, plan), ensure_ascii=False, default=str),
    )
    session.add(order)
    session.flush()
    return order


def mock_pay_order(session: Session, user: User, order_id: str) -> PaymentOrder:
    order = session.get(PaymentOrder, order_id)
    if not order or order.user_id != user.id:
        raise HTTPException(status_code=404, detail="订单不存在")
    if order.status == "paid":
        return order
    try:
        _lock_for_session(session, "order-pay", order_id)
    except RuntimeLockBusyError as exc:
        raise HTTPException(status_code=409, detail="订单支付正在处理中，请稍后重试") from exc
    session.refresh(order)
    if order.status == "paid":
        return order

    order.status = "paid"
    order.paid_at = utcnow()
    if order.product_type == "bean_pack":
        pack = session.get(BeanPack, order.bean_pack_id)
        if not pack or not pack.enabled:
            raise HTTPException(status_code=404, detail="补豆包不存在")
        subscription = active_subscription(session, user)
        expires_at = subscription.ends_at if subscription and subscription.ends_at else utcnow() + timedelta(days=30)
        grant_beans(
            session,
            user.id,
            amount=pack.beans,
            expires_at=expires_at,
            source_type="bean_pack",
            source_id=order.id,
            source_key=f"order:{order.id}",
            description=pack.name,
        )
        create_notification(
            session,
            user.id,
            title="补豆包已到账",
            body=f"{pack.name} 已添加 {pack.beans} 豆。",
            category="payment",
            metadata={"order_id": order.id, "beans": pack.beans},
        )
        return order

    plan = session.get(SubscriptionPlan, order.plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="套餐不存在")
    duration = timedelta(days=365 if order.billing_cycle == "yearly" else 31)
    ends_at = utcnow() + duration
    subscription = UserSubscription(
        user_id=user.id,
        plan_id=plan.id,
        billing_cycle=order.billing_cycle,
        status="active",
        starts_at=utcnow(),
        ends_at=ends_at,
        source_order_id=order.id,
    )
    session.add(subscription)
    session.flush()
    user.current_plan_code = plan.code
    grant_beans(
        session,
        user.id,
        amount=int(plan.beans or 0),
        expires_at=ends_at,
        source_type="subscription",
        source_id=subscription.id,
        source_key=f"subscription:{subscription.id}",
        description=f"{plan.name}订阅豆子",
    )
    create_notification(
        session,
        user.id,
        title="订阅已生效",
        body=f"{plan.name} 已开通，{plan.beans or 0} 豆已添加。",
        category="payment",
        metadata={"order_id": order.id, "plan_code": plan.code, "beans": plan.beans or 0},
    )
    return order


def serialize_order(session: Session, order: PaymentOrder) -> dict[str, Any]:
    plan = session.get(SubscriptionPlan, order.plan_id) if order.plan_id else None
    pack = session.get(BeanPack, order.bean_pack_id) if order.bean_pack_id else None
    return {
        "id": order.id,
        "order_no": order.order_no,
        "product_type": order.product_type,
        "bean_pack_code": pack.code if pack else "",
        "bean_pack_name": pack.name if pack else "",
        "beans": pack.beans if pack else plan.beans if plan else None,
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
