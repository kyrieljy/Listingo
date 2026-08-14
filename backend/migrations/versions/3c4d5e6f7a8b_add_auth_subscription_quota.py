"""add_auth_subscription_quota

Revision ID: 3c4d5e6f7a8b
Revises: 2a8f76b1d9c4
Create Date: 2026-08-12 23:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "3c4d5e6f7a8b"
down_revision: Union[str, Sequence[str], None] = "2a8f76b1d9c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "app_user",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("phone", sa.String(length=32), nullable=False),
        sa.Column("username", sa.String(length=80), nullable=False),
        sa.Column("email", sa.String(length=160), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("avatar_initials", sa.String(length=8), nullable=False),
        sa.Column("uid", sa.String(length=32), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=True),
        sa.Column("password_set", sa.Boolean(), nullable=False),
        sa.Column("first_password_pending", sa.Boolean(), nullable=False),
        sa.Column("gender", sa.String(length=20), nullable=False),
        sa.Column("bio", sa.Text(), nullable=False),
        sa.Column("current_plan_code", sa.String(length=40), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_app_user_phone"), "app_user", ["phone"], unique=True)
    op.create_index(op.f("ix_app_user_username"), "app_user", ["username"], unique=True)
    op.create_index(op.f("ix_app_user_uid"), "app_user", ["uid"], unique=True)
    op.create_index(op.f("ix_app_user_role"), "app_user", ["role"], unique=False)
    op.create_index(op.f("ix_app_user_status"), "app_user", ["status"], unique=False)
    op.create_index(op.f("ix_app_user_current_plan_code"), "app_user", ["current_plan_code"], unique=False)

    op.create_table(
        "sms_config",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("debug_mode", sa.Boolean(), nullable=False),
        sa.Column("region_id", sa.String(length=80), nullable=False),
        sa.Column("sign_name", sa.String(length=120), nullable=False),
        sa.Column("login_template_code", sa.String(length=80), nullable=False),
        sa.Column("register_template_code", sa.String(length=80), nullable=False),
        sa.Column("change_phone_template_code", sa.String(length=80), nullable=False),
        sa.Column("admin_template_code", sa.String(length=80), nullable=False),
        sa.Column("access_key_id", sa.String(length=200), nullable=False),
        sa.Column("encrypted_access_key_secret", sa.Text(), nullable=True),
        sa.Column("code_ttl_seconds", sa.Integer(), nullable=False),
        sa.Column("cooldown_seconds", sa.Integer(), nullable=False),
        sa.Column("daily_limit_per_phone", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "subscription_plan",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("badge", sa.String(length=80), nullable=False),
        sa.Column("cta", sa.String(length=80), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("visible", sa.Boolean(), nullable=False),
        sa.Column("is_internal", sa.Boolean(), nullable=False),
        sa.Column("is_enterprise", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("features_json", sa.Text(), nullable=False),
        sa.Column("contact_text", sa.Text(), nullable=False),
        sa.Column("contact_phone", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_subscription_plan_code"), "subscription_plan", ["code"], unique=True)
    op.create_index(op.f("ix_subscription_plan_enabled"), "subscription_plan", ["enabled"], unique=False)
    op.create_index(op.f("ix_subscription_plan_visible"), "subscription_plan", ["visible"], unique=False)
    op.create_index(op.f("ix_subscription_plan_is_internal"), "subscription_plan", ["is_internal"], unique=False)
    op.create_index(op.f("ix_subscription_plan_is_enterprise"), "subscription_plan", ["is_enterprise"], unique=False)

    for table_name in ("asset", "generation_job", "video_job", "aplus_job", "batch_job"):
        op.add_column(table_name, sa.Column("user_id", sa.String(length=36), nullable=True))
        op.create_index(op.f(f"ix_{table_name}_user_id"), table_name, ["user_id"], unique=False)

    op.create_table(
        "user_session",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("session_token_hash", sa.String(length=64), nullable=False),
        sa.Column("refresh_token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("refresh_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip_address", sa.String(length=80), nullable=False),
        sa.Column("user_agent", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_user_session_user_id"), "user_session", ["user_id"], unique=False)
    op.create_index(op.f("ix_user_session_session_token_hash"), "user_session", ["session_token_hash"], unique=True)
    op.create_index(op.f("ix_user_session_refresh_token_hash"), "user_session", ["refresh_token_hash"], unique=True)
    op.create_index(op.f("ix_user_session_expires_at"), "user_session", ["expires_at"], unique=False)
    op.create_index(op.f("ix_user_session_refresh_expires_at"), "user_session", ["refresh_expires_at"], unique=False)

    op.create_table(
        "login_event",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column("phone", sa.String(length=32), nullable=False),
        sa.Column("method", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("ip_address", sa.String(length=80), nullable=False),
        sa.Column("user_agent", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_login_event_user_id"), "login_event", ["user_id"], unique=False)
    op.create_index(op.f("ix_login_event_phone"), "login_event", ["phone"], unique=False)
    op.create_index(op.f("ix_login_event_method"), "login_event", ["method"], unique=False)
    op.create_index(op.f("ix_login_event_status"), "login_event", ["status"], unique=False)
    op.create_index(op.f("ix_login_event_created_at"), "login_event", ["created_at"], unique=False)

    op.create_table(
        "sms_verification_code",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("phone", sa.String(length=32), nullable=False),
        sa.Column("purpose", sa.String(length=30), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("send_ip", sa.String(length=80), nullable=False),
        sa.Column("provider_message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_sms_verification_code_phone"), "sms_verification_code", ["phone"], unique=False)
    op.create_index(op.f("ix_sms_verification_code_purpose"), "sms_verification_code", ["purpose"], unique=False)
    op.create_index(op.f("ix_sms_verification_code_expires_at"), "sms_verification_code", ["expires_at"], unique=False)

    op.create_table(
        "plan_price",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("plan_id", sa.String(length=36), nullable=False),
        sa.Column("billing_cycle", sa.String(length=20), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=True),
        sa.Column("currency", sa.String(length=12), nullable=False),
        sa.Column("price_label", sa.String(length=80), nullable=False),
        sa.Column("period_label", sa.String(length=40), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["plan_id"], ["subscription_plan.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_plan_price_plan_id"), "plan_price", ["plan_id"], unique=False)
    op.create_index(op.f("ix_plan_price_billing_cycle"), "plan_price", ["billing_cycle"], unique=False)

    op.create_table(
        "plan_quota_rule",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("plan_id", sa.String(length=36), nullable=False),
        sa.Column("action_key", sa.String(length=60), nullable=False),
        sa.Column("action_label", sa.String(length=120), nullable=False),
        sa.Column("unit", sa.String(length=40), nullable=False),
        sa.Column("monthly_limit", sa.Integer(), nullable=True),
        sa.Column("cost_multiplier", sa.Integer(), nullable=False),
        sa.Column("warning_threshold", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["plan_id"], ["subscription_plan.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_plan_quota_rule_plan_id"), "plan_quota_rule", ["plan_id"], unique=False)
    op.create_index(op.f("ix_plan_quota_rule_action_key"), "plan_quota_rule", ["action_key"], unique=False)

    op.create_table(
        "user_subscription",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("plan_id", sa.String(length=36), nullable=False),
        sa.Column("billing_cycle", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("auto_renew", sa.Boolean(), nullable=False),
        sa.Column("source_order_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["plan_id"], ["subscription_plan.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_user_subscription_user_id"), "user_subscription", ["user_id"], unique=False)
    op.create_index(op.f("ix_user_subscription_plan_id"), "user_subscription", ["plan_id"], unique=False)
    op.create_index(op.f("ix_user_subscription_status"), "user_subscription", ["status"], unique=False)
    op.create_index(op.f("ix_user_subscription_source_order_id"), "user_subscription", ["source_order_id"], unique=False)

    op.create_table(
        "payment_order",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("order_no", sa.String(length=40), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("plan_id", sa.String(length=36), nullable=False),
        sa.Column("billing_cycle", sa.String(length=20), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=True),
        sa.Column("currency", sa.String(length=12), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("snapshot_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["plan_id"], ["subscription_plan.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_payment_order_order_no"), "payment_order", ["order_no"], unique=True)
    op.create_index(op.f("ix_payment_order_user_id"), "payment_order", ["user_id"], unique=False)
    op.create_index(op.f("ix_payment_order_plan_id"), "payment_order", ["plan_id"], unique=False)
    op.create_index(op.f("ix_payment_order_status"), "payment_order", ["status"], unique=False)

    op.create_table(
        "quota_ledger",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("action_key", sa.String(length=60), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("ref_type", sa.String(length=40), nullable=False),
        sa.Column("ref_id", sa.String(length=36), nullable=False),
        sa.Column("period", sa.String(length=7), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_quota_ledger_user_id"), "quota_ledger", ["user_id"], unique=False)
    op.create_index(op.f("ix_quota_ledger_action_key"), "quota_ledger", ["action_key"], unique=False)
    op.create_index(op.f("ix_quota_ledger_status"), "quota_ledger", ["status"], unique=False)
    op.create_index(op.f("ix_quota_ledger_ref_type"), "quota_ledger", ["ref_type"], unique=False)
    op.create_index(op.f("ix_quota_ledger_ref_id"), "quota_ledger", ["ref_id"], unique=False)
    op.create_index(op.f("ix_quota_ledger_period"), "quota_ledger", ["period"], unique=False)
    op.create_index(op.f("ix_quota_ledger_created_at"), "quota_ledger", ["created_at"], unique=False)

    op.create_table(
        "notification",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("unread", sa.Boolean(), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_notification_user_id"), "notification", ["user_id"], unique=False)
    op.create_index(op.f("ix_notification_category"), "notification", ["category"], unique=False)
    op.create_index(op.f("ix_notification_unread"), "notification", ["unread"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_notification_unread"), table_name="notification")
    op.drop_index(op.f("ix_notification_category"), table_name="notification")
    op.drop_index(op.f("ix_notification_user_id"), table_name="notification")
    op.drop_table("notification")
    op.drop_index(op.f("ix_quota_ledger_created_at"), table_name="quota_ledger")
    op.drop_index(op.f("ix_quota_ledger_period"), table_name="quota_ledger")
    op.drop_index(op.f("ix_quota_ledger_ref_id"), table_name="quota_ledger")
    op.drop_index(op.f("ix_quota_ledger_ref_type"), table_name="quota_ledger")
    op.drop_index(op.f("ix_quota_ledger_status"), table_name="quota_ledger")
    op.drop_index(op.f("ix_quota_ledger_action_key"), table_name="quota_ledger")
    op.drop_index(op.f("ix_quota_ledger_user_id"), table_name="quota_ledger")
    op.drop_table("quota_ledger")
    op.drop_index(op.f("ix_payment_order_status"), table_name="payment_order")
    op.drop_index(op.f("ix_payment_order_plan_id"), table_name="payment_order")
    op.drop_index(op.f("ix_payment_order_user_id"), table_name="payment_order")
    op.drop_index(op.f("ix_payment_order_order_no"), table_name="payment_order")
    op.drop_table("payment_order")
    op.drop_index(op.f("ix_user_subscription_source_order_id"), table_name="user_subscription")
    op.drop_index(op.f("ix_user_subscription_status"), table_name="user_subscription")
    op.drop_index(op.f("ix_user_subscription_plan_id"), table_name="user_subscription")
    op.drop_index(op.f("ix_user_subscription_user_id"), table_name="user_subscription")
    op.drop_table("user_subscription")
    op.drop_index(op.f("ix_plan_quota_rule_action_key"), table_name="plan_quota_rule")
    op.drop_index(op.f("ix_plan_quota_rule_plan_id"), table_name="plan_quota_rule")
    op.drop_table("plan_quota_rule")
    op.drop_index(op.f("ix_plan_price_billing_cycle"), table_name="plan_price")
    op.drop_index(op.f("ix_plan_price_plan_id"), table_name="plan_price")
    op.drop_table("plan_price")
    op.drop_index(op.f("ix_sms_verification_code_expires_at"), table_name="sms_verification_code")
    op.drop_index(op.f("ix_sms_verification_code_purpose"), table_name="sms_verification_code")
    op.drop_index(op.f("ix_sms_verification_code_phone"), table_name="sms_verification_code")
    op.drop_table("sms_verification_code")
    op.drop_index(op.f("ix_login_event_created_at"), table_name="login_event")
    op.drop_index(op.f("ix_login_event_status"), table_name="login_event")
    op.drop_index(op.f("ix_login_event_method"), table_name="login_event")
    op.drop_index(op.f("ix_login_event_phone"), table_name="login_event")
    op.drop_index(op.f("ix_login_event_user_id"), table_name="login_event")
    op.drop_table("login_event")
    op.drop_index(op.f("ix_user_session_refresh_expires_at"), table_name="user_session")
    op.drop_index(op.f("ix_user_session_expires_at"), table_name="user_session")
    op.drop_index(op.f("ix_user_session_refresh_token_hash"), table_name="user_session")
    op.drop_index(op.f("ix_user_session_session_token_hash"), table_name="user_session")
    op.drop_index(op.f("ix_user_session_user_id"), table_name="user_session")
    op.drop_table("user_session")
    for table_name in ("batch_job", "aplus_job", "video_job", "generation_job", "asset"):
        op.drop_index(op.f(f"ix_{table_name}_user_id"), table_name=table_name)
        op.drop_column(table_name, "user_id")
    op.drop_index(op.f("ix_subscription_plan_is_enterprise"), table_name="subscription_plan")
    op.drop_index(op.f("ix_subscription_plan_is_internal"), table_name="subscription_plan")
    op.drop_index(op.f("ix_subscription_plan_visible"), table_name="subscription_plan")
    op.drop_index(op.f("ix_subscription_plan_enabled"), table_name="subscription_plan")
    op.drop_index(op.f("ix_subscription_plan_code"), table_name="subscription_plan")
    op.drop_table("subscription_plan")
    op.drop_table("sms_config")
    op.drop_index(op.f("ix_app_user_current_plan_code"), table_name="app_user")
    op.drop_index(op.f("ix_app_user_status"), table_name="app_user")
    op.drop_index(op.f("ix_app_user_role"), table_name="app_user")
    op.drop_index(op.f("ix_app_user_uid"), table_name="app_user")
    op.drop_index(op.f("ix_app_user_username"), table_name="app_user")
    op.drop_index(op.f("ix_app_user_phone"), table_name="app_user")
    op.drop_table("app_user")
