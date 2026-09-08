from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from sqlalchemy import select

from backend.app.models import (
    AplusItem,
    AplusJob,
    BeanGrant,
    BeanLedger,
    GenerationItem,
    GenerationJob,
    PlanQuotaRule,
    Prompt,
    PromptVersion,
    QuotaLedger,
    SubscriptionPlan,
    User,
    UserSubscription,
    Workflow,
    utcnow,
)
from backend.app.services.aplus_jobs import sync_aplus_quota
from backend.app.services.jobs import sync_generation_quota
from backend.app.services.subscriptions import (
    BEANS_PER_IMAGE,
    available_beans,
    create_payment_order,
    grant_beans,
    migrate_legacy_quotas,
    mock_pay_order,
    plan_entitlement,
    reserve_beans,
    user_plan,
)


def _user_id(client, *, plan_code: str = "free", role: str = "user") -> str:
    suffix = uuid4().hex[:12]
    user_id = f"bill-{suffix}"
    with client.app.state.session_factory() as session:
        session.add(
            User(
                id=user_id,
                phone=f"137{suffix}",
                username=user_id,
                display_name="Billing User",
                uid=user_id.upper(),
                role=role,
                current_plan_code=plan_code,
            )
        )
        session.commit()
    return user_id


def _user(client, user_id: str) -> User:
    with client.app.state.session_factory() as session:
        user = session.get(User, user_id)
        assert user is not None
        return user


def test_v1_catalog_and_wallet_ledger_precision(client) -> None:
    plans = client.get("/api/v1/subscription/plans").json()
    plan_codes = [plan["code"] for plan in plans]
    assert plan_codes == [
        "monthly_basic",
        "monthly_standard",
        "monthly_pro",
        "yearly_basic",
        "yearly_standard",
        "yearly_flagship",
        "enterprise_custom",
    ]
    assert {plan["code"] for plan in plans if plan["recommended"]} == {"monthly_standard", "yearly_standard"}

    packs = client.get("/api/v1/bean-packs").json()
    assert [(pack["code"], pack["beans"], pack["recommended"]) for pack in packs] == [
        ("beans_50", 360, False),
        ("beans_129", 960, False),
        ("beans_399", 3120, True),
        ("beans_999", 8400, False),
    ]

    user_id = _user_id(client)
    with client.app.state.session_factory() as session:
        user = session.get(User, user_id)
        assert user is not None
        grant_beans(session, user_id, amount=84, expires_at=None, source_type="test", source_id=None, source_key=f"test:{user_id}")

        prompt = session.scalar(select(Prompt).where(Prompt.code == "ecommerce-meta"))
        workflow = session.scalar(select(Workflow).where(Workflow.code == "product-suite-v1"))
        assert prompt and prompt.active_version_id and workflow and workflow.active_version_id
        job = GenerationJob(
            user_id=user_id,
            status="partial_failed",
            dry_run=False,
            params_json="{}",
            asset_ids_json="[]",
            count=7,
            prompt_version_id=prompt.active_version_id,
            workflow_version_id=workflow.active_version_id,
        )
        session.add(job)
        session.flush()
        statuses = ["succeeded"] * 3 + ["failed"] * 4
        for index, status in enumerate(statuses):
            session.add(
                GenerationItem(
                    job_id=job.id,
                    index=index,
                    image_type="main",
                    prompt_text="test",
                    status=status,
                )
            )
        session.flush()
        reserve_beans(session, user, amount=84, ref_type="generation_job", ref_id=job.id, description="initial generation")
        sync_generation_quota(session, job)
        initial = session.scalars(select(BeanLedger).where(BeanLedger.ref_id == job.id)).one()
        assert (initial.confirmed_amount, initial.released_amount, initial.status) == (36, 48, "settled")
        session.commit()
        user = session.get(User, user_id)
        job = session.get(GenerationJob, job.id)
        assert user is not None and job is not None
        assert available_beans(session, user_id) == 48

        failed_ids = [item.id for item in job.items if item.status == "failed"]
        reserve_beans(
            session,
            user,
            amount=48,
            ref_type="generation_job",
            ref_id=job.id,
            description="retry generation",
            refs=failed_ids,
        )
        for item in job.items:
            if item.id in failed_ids[:2]:
                item.status = "succeeded"
        session.flush()
        sync_generation_quota(session, job)
        ledgers = session.scalars(select(BeanLedger).where(BeanLedger.ref_id == job.id).order_by(BeanLedger.created_at)).all()
        assert [(row.confirmed_amount, row.released_amount) for row in ledgers] == [(36, 48), (24, 24)]
        assert available_beans(session, user_id) == 24
        assert available_beans(session, user_id) == 24


def test_aplus_retry_ledger_only_charges_retried_successes(client) -> None:
    user_id = _user_id(client)
    with client.app.state.session_factory() as session:
        user = session.get(User, user_id)
        assert user is not None
        grant_beans(session, user_id, amount=48, expires_at=None, source_type="test", source_id=None, source_key=f"test:{user_id}")
        prompt = session.scalar(select(Prompt).where(Prompt.code == "aplus-meta"))
        assert prompt and prompt.active_version_id
        job = AplusJob(
            user_id=user_id,
            job_type="generation",
            status="failed",
            dry_run=False,
            params_json="{}",
            asset_ids_json="[]",
            count=4,
            prompt_version_id=prompt.active_version_id,
        )
        session.add(job)
        session.flush()
        for index in range(4):
            session.add(
                AplusItem(
                    job_id=job.id,
                    index=index,
                    module_index=index,
                    module_name=f"Module {index}",
                    status="failed",
                )
            )
        session.flush()
        reserve_beans(session, user, amount=48, ref_type="aplus_job", ref_id=job.id, description="initial A+")
        sync_aplus_quota(session, job)

        session.commit()
        user = session.get(User, user_id)
        job = session.get(AplusJob, job.id)
        assert user is not None and job is not None
        reserve_beans(
            session,
            user,
            amount=48,
            ref_type="aplus_job",
            ref_id=job.id,
            description="retry A+",
            refs=[item.id for item in job.items],
        )
        for item in job.items[:2]:
            item.status = "succeeded"
        job.status = "partial_failed"
        session.flush()
        sync_aplus_quota(session, job)
        ledgers = session.scalars(select(BeanLedger).where(BeanLedger.ref_id == job.id).order_by(BeanLedger.created_at)).all()
        assert [(row.confirmed_amount, row.released_amount) for row in ledgers] == [(0, 48), (24, 24)]
        assert available_beans(session, user_id) == 24


def test_subscription_and_bean_pack_payments_have_explicit_expiry(client) -> None:
    subscriber_id = _user_id(client)
    visitor_id = _user_id(client)
    with client.app.state.session_factory() as session:
        subscriber = session.get(User, subscriber_id)
        visitor = session.get(User, visitor_id)
        assert subscriber and visitor

        subscription_order = create_payment_order(session, subscriber, plan_code="monthly_standard", billing_cycle="monthly")
        mock_pay_order(session, subscriber, subscription_order.id)
        subscription = session.scalar(select(UserSubscription).where(UserSubscription.user_id == subscriber_id))
        assert subscription and subscription.ends_at
        subscription_grant = session.scalar(select(BeanGrant).where(BeanGrant.user_id == subscriber_id))
        assert subscription_grant
        assert (subscription_grant.amount, subscription_grant.remaining_beans) == (1560, 1560)
        assert subscription_grant.expires_at == subscription.ends_at

        member_pack_order = create_payment_order(session, subscriber, bean_pack_code="beans_50")
        mock_pay_order(session, subscriber, member_pack_order.id)
        member_pack = session.scalar(select(BeanGrant).where(BeanGrant.source_type == "bean_pack", BeanGrant.user_id == subscriber_id))
        assert member_pack and member_pack.expires_at == subscription.ends_at

        visitor_pack_order = create_payment_order(session, visitor, bean_pack_code="beans_50")
        mock_pay_order(session, visitor, visitor_pack_order.id)
        visitor_pack = session.scalar(select(BeanGrant).where(BeanGrant.user_id == visitor_id))
        assert visitor_pack and visitor_pack.expires_at
        assert timedelta(days=29) < visitor_pack.expires_at - utcnow() <= timedelta(days=30)

        grant_count = len(session.scalars(select(BeanGrant).where(BeanGrant.user_id == subscriber_id)).all())
        mock_pay_order(session, subscriber, subscription_order.id)
        assert len(session.scalars(select(BeanGrant).where(BeanGrant.user_id == subscriber_id)).all()) == grant_count


def test_legacy_b_plan_is_idempotent_and_old_paid_subscription_has_no_v1_entitlement(client) -> None:
    user_id = _user_id(client)
    with client.app.state.session_factory() as session:
        legacy_plan = SubscriptionPlan(code="standard", name="Legacy Standard", billing_cycle="legacy", beans=None)
        session.add(legacy_plan)
        session.flush()
        ends_at = utcnow() + timedelta(days=10)
        subscription = UserSubscription(
            user_id=user_id,
            plan_id=legacy_plan.id,
            billing_cycle="monthly",
            status="active",
            starts_at=utcnow() - timedelta(days=1),
            ends_at=ends_at,
        )
        session.add(subscription)
        session.flush()
        rules = [
            ("image_generation", 10, 2, "reserved"),
            ("aplus_generation", 4, 1, "confirmed"),
            ("edit_generation", 2, 2, "released"),
            ("batch_suite", 999, 10, "reserved"),
            ("video_generation", 999, 10, "reserved"),
        ]
        period = utcnow().strftime("%Y-%m")
        for action, limit, used, status in rules:
            session.add(PlanQuotaRule(plan_id=legacy_plan.id, action_key=action, action_label=action, monthly_limit=limit))
            for index in range(used):
                session.add(
                    QuotaLedger(
                        user_id=user_id,
                        action_key=action,
                        amount=1,
                        status=status,
                        period=period,
                    )
                )
        session.flush()
        migrate_legacy_quotas(session)
        grants = session.scalars(select(BeanGrant).where(BeanGrant.user_id == user_id)).all()
        assert len(grants) == 1
        assert grants[0].amount == 13 * BEANS_PER_IMAGE
        assert grants[0].expires_at == ends_at

        migrate_legacy_quotas(session)
        assert len(session.scalars(select(BeanGrant).where(BeanGrant.user_id == user_id)).all()) == 1

        user = session.get(User, user_id)
        assert user is not None
        assert user_plan(session, user).code == "free"
        assert plan_entitlement(session, user, "batch_generation") is False


def test_public_video_is_hidden_for_users_and_enterprise_lead_flow(client) -> None:
    phone = "13912345678"
    sent = client.post("/api/v1/auth/sms/send", json={"phone": phone, "purpose": "register"})
    assert sent.status_code == 200
    login = client.post("/api/v1/auth/sms/login", json={"phone": phone, "mode": "register", "code": sent.json()["debug_code"]})
    assert login.status_code == 200

    client.app.state.settings.testing = False
    try:
        assert client.get("/api/v1/video-jobs").status_code == 404
        client.cookies.clear()
        lead_payload = {
            "name": "王女士",
            "phone": "13912345678",
            "wechat": "listingo",
            "company_or_shop": "Listingo Store",
            "monthly_usage": "1000_5000",
            "requirement": "需要批量商品图",
        }
        created = client.post("/api/v1/enterprise-leads", json=lead_payload)
        assert created.status_code == 201, created.text
        assert created.json()["user_id"] is None
        assert client.post("/api/v1/enterprise-leads", json={**lead_payload, "phone": "not-a-phone"}).status_code == 422

        admin_sent = client.post("/api/v1/auth/sms/send", json={"phone": "18928268686", "purpose": "login"})
        assert admin_sent.status_code == 200
        admin_login = client.post(
            "/api/v1/auth/sms/login",
            json={"phone": "18928268686", "mode": "login", "code": admin_sent.json()["debug_code"]},
        )
        assert admin_login.status_code == 200
        lead_id = created.json()["id"]
        assert client.patch(f"/api/v1/admin/enterprise-leads/{lead_id}/status", json={"status": "following"}).status_code == 200
        assert client.patch(f"/api/v1/admin/enterprise-leads/{lead_id}/note", json={"note": "已电话联系"}).status_code == 200
        exported = client.get("/api/v1/admin/enterprise-leads/export")
        assert exported.status_code == 200
        assert exported.content.startswith(b"\xef\xbb\xbf")
        assert "Listingo Store".encode() in exported.content
    finally:
        client.app.state.settings.testing = True


def test_batch_entitlement_matrix_ignores_batch_upload(client) -> None:
    expected = {
        "free": False,
        "monthly_basic": False,
        "monthly_standard": True,
        "monthly_pro": True,
        "yearly_basic": True,
        "yearly_standard": True,
        "yearly_flagship": True,
        "enterprise_custom": True,
    }
    with client.app.state.session_factory() as session:
        for code, allowed in expected.items():
            user_id = _user_id(client, plan_code=code)
            user = session.get(User, user_id)
            plan = session.scalar(select(SubscriptionPlan).where(SubscriptionPlan.code == code))
            assert plan is not None
            if code != "free":
                session.add(
                    UserSubscription(
                        user_id=user_id,
                        plan_id=plan.id,
                        billing_cycle=plan.billing_cycle,
                        status="active",
                        starts_at=utcnow(),
                        ends_at=utcnow() + timedelta(days=30),
                    )
                )
                session.flush()
            assert user is not None
            assert plan_entitlement(session, user, "batch_generation") is allowed

            # A bean pack only adds balance and must not unlock the feature.
            grant_beans(
                session,
                user_id,
                amount=360,
                expires_at=utcnow() + timedelta(days=30),
                source_type="bean_pack",
                source_id=None,
                source_key=f"matrix:{user_id}",
            )
            assert plan_entitlement(session, user, "batch_generation") is allowed
