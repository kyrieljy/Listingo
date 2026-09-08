"""commercial billing rules v1

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-09-06 00:00:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "e2f3a4b5c6d7"
down_revision: Union[str, Sequence[str], None] = "d1e2f3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("subscription_plan", sa.Column("billing_cycle", sa.String(length=20), nullable=False, server_default="legacy"))
    op.add_column("subscription_plan", sa.Column("beans", sa.Integer(), nullable=True))
    op.add_column("subscription_plan", sa.Column("recommended", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("subscription_plan", sa.Column("contact_sales", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("subscription_plan", sa.Column("entitlements_json", sa.Text(), nullable=False, server_default="{}"))
    op.create_index(op.f("ix_subscription_plan_billing_cycle"), "subscription_plan", ["billing_cycle"], unique=False)
    op.create_index(op.f("ix_subscription_plan_recommended"), "subscription_plan", ["recommended"], unique=False)
    op.create_index(op.f("ix_subscription_plan_contact_sales"), "subscription_plan", ["contact_sales"], unique=False)

    now = sa.text("now()")
    op.create_table(
        "bean_pack",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=12), nullable=False, server_default="CNY"),
        sa.Column("beans", sa.Integer(), nullable=False),
        sa.Column("recommended", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("visible", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_bean_pack_code"), "bean_pack", ["code"], unique=True)
    op.create_index(op.f("ix_bean_pack_recommended"), "bean_pack", ["recommended"], unique=False)
    op.create_index(op.f("ix_bean_pack_enabled"), "bean_pack", ["enabled"], unique=False)
    op.create_index(op.f("ix_bean_pack_visible"), "bean_pack", ["visible"], unique=False)

    op.create_table(
        "commercial_billing_config",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("beans_per_image", sa.Integer(), nullable=False, server_default="12"),
        sa.Column("refund_on_system_failure", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("video_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_commercial_billing_config_version"), "commercial_billing_config", ["version"], unique=False)

    op.create_table(
        "bean_grant",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("remaining_beans", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_type", sa.String(length=40), nullable=False, server_default="subscription"),
        sa.Column("source_id", sa.String(length=36), nullable=True),
        sa.Column("source_key", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_bean_grant_user_id"), "bean_grant", ["user_id"], unique=False)
    op.create_index(op.f("ix_bean_grant_expires_at"), "bean_grant", ["expires_at"], unique=False)
    op.create_index(op.f("ix_bean_grant_source_type"), "bean_grant", ["source_type"], unique=False)
    op.create_index(op.f("ix_bean_grant_source_id"), "bean_grant", ["source_id"], unique=False)
    op.create_index(op.f("ix_bean_grant_source_key"), "bean_grant", ["source_key"], unique=True)

    op.create_table(
        "bean_ledger",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("ref_type", sa.String(length=40), nullable=False),
        sa.Column("ref_id", sa.String(length=80), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("confirmed_amount", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("released_amount", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="reserved"),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("refs_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("allocations_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_bean_ledger_user_id"), "bean_ledger", ["user_id"], unique=False)
    op.create_index(op.f("ix_bean_ledger_ref_type"), "bean_ledger", ["ref_type"], unique=False)
    op.create_index(op.f("ix_bean_ledger_ref_id"), "bean_ledger", ["ref_id"], unique=False)
    op.create_index(op.f("ix_bean_ledger_status"), "bean_ledger", ["status"], unique=False)

    op.create_table(
        "enterprise_lead",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("contact_name", sa.String(length=80), nullable=False),
        sa.Column("phone", sa.String(length=32), nullable=False),
        sa.Column("wechat", sa.String(length=80), nullable=False, server_default=""),
        sa.Column("company_or_shop", sa.String(length=200), nullable=False),
        sa.Column("monthly_usage", sa.String(length=30), nullable=False),
        sa.Column("requirement", sa.Text(), nullable=False, server_default=""),
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column("account_phone", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("source", sa.String(length=80), nullable=False, server_default="enterprise_custom_plan"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_enterprise_lead_contact_name"), "enterprise_lead", ["contact_name"], unique=False)
    op.create_index(op.f("ix_enterprise_lead_phone"), "enterprise_lead", ["phone"], unique=False)
    op.create_index(op.f("ix_enterprise_lead_company_or_shop"), "enterprise_lead", ["company_or_shop"], unique=False)
    op.create_index(op.f("ix_enterprise_lead_monthly_usage"), "enterprise_lead", ["monthly_usage"], unique=False)
    op.create_index(op.f("ix_enterprise_lead_user_id"), "enterprise_lead", ["user_id"], unique=False)
    op.create_index(op.f("ix_enterprise_lead_account_phone"), "enterprise_lead", ["account_phone"], unique=False)
    op.create_index(op.f("ix_enterprise_lead_status"), "enterprise_lead", ["status"], unique=False)

    with op.batch_alter_table("payment_order") as batch:
        batch.alter_column("plan_id", existing_type=sa.String(length=36), nullable=True)
        batch.add_column(sa.Column("product_type", sa.String(length=20), nullable=False, server_default="subscription"))
        batch.add_column(sa.Column("bean_pack_id", sa.String(length=36), nullable=True))
        batch.create_foreign_key("fk_payment_order_bean_pack", "bean_pack", ["bean_pack_id"], ["id"])
    op.create_index(op.f("ix_payment_order_product_type"), "payment_order", ["product_type"], unique=False)
    op.create_index(op.f("ix_payment_order_bean_pack_id"), "payment_order", ["bean_pack_id"], unique=False)

    # Older sensitive-word migrations expressed unique columns as both a
    # constraint and a non-unique index; ORM metadata uses one unique index.
    op.drop_constraint("uq_sensitive_word_normalized_term", "sensitive_word")
    op.drop_index(op.f("ix_sensitive_word_normalized_term"), table_name="sensitive_word")
    op.create_index(op.f("ix_sensitive_word_normalized_term"), "sensitive_word", ["normalized_term"], unique=True)
    op.drop_constraint("uq_sensitive_word_snapshot_source_digest", "sensitive_word_snapshot")
    op.drop_index(op.f("ix_sensitive_word_snapshot_source_digest"), table_name="sensitive_word_snapshot")
    op.create_index(op.f("ix_sensitive_word_snapshot_source_digest"), "sensitive_word_snapshot", ["source_digest"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_sensitive_word_snapshot_source_digest"), table_name="sensitive_word_snapshot")
    op.create_index(op.f("ix_sensitive_word_snapshot_source_digest"), "sensitive_word_snapshot", ["source_digest"], unique=False)
    op.create_unique_constraint("uq_sensitive_word_snapshot_source_digest", "sensitive_word_snapshot", ["source_digest"])
    op.drop_index(op.f("ix_sensitive_word_normalized_term"), table_name="sensitive_word")
    op.create_index(op.f("ix_sensitive_word_normalized_term"), "sensitive_word", ["normalized_term"], unique=False)
    op.create_unique_constraint("uq_sensitive_word_normalized_term", "sensitive_word", ["normalized_term"])

    op.drop_index(op.f("ix_payment_order_bean_pack_id"), table_name="payment_order")
    op.drop_index(op.f("ix_payment_order_product_type"), table_name="payment_order")
    with op.batch_alter_table("payment_order") as batch:
        batch.drop_constraint("fk_payment_order_bean_pack", type_="foreignkey")
        batch.drop_column("bean_pack_id")
        batch.drop_column("product_type")
        batch.alter_column("plan_id", existing_type=sa.String(length=36), nullable=False)

    op.drop_index(op.f("ix_enterprise_lead_status"), table_name="enterprise_lead")
    op.drop_index(op.f("ix_enterprise_lead_account_phone"), table_name="enterprise_lead")
    op.drop_index(op.f("ix_enterprise_lead_user_id"), table_name="enterprise_lead")
    op.drop_index(op.f("ix_enterprise_lead_monthly_usage"), table_name="enterprise_lead")
    op.drop_index(op.f("ix_enterprise_lead_company_or_shop"), table_name="enterprise_lead")
    op.drop_index(op.f("ix_enterprise_lead_phone"), table_name="enterprise_lead")
    op.drop_index(op.f("ix_enterprise_lead_contact_name"), table_name="enterprise_lead")
    op.drop_table("enterprise_lead")

    op.drop_index(op.f("ix_bean_ledger_status"), table_name="bean_ledger")
    op.drop_index(op.f("ix_bean_ledger_ref_id"), table_name="bean_ledger")
    op.drop_index(op.f("ix_bean_ledger_ref_type"), table_name="bean_ledger")
    op.drop_index(op.f("ix_bean_ledger_user_id"), table_name="bean_ledger")
    op.drop_table("bean_ledger")

    op.drop_index(op.f("ix_bean_grant_source_key"), table_name="bean_grant")
    op.drop_index(op.f("ix_bean_grant_source_id"), table_name="bean_grant")
    op.drop_index(op.f("ix_bean_grant_source_type"), table_name="bean_grant")
    op.drop_index(op.f("ix_bean_grant_expires_at"), table_name="bean_grant")
    op.drop_index(op.f("ix_bean_grant_user_id"), table_name="bean_grant")
    op.drop_table("bean_grant")

    op.drop_index(op.f("ix_commercial_billing_config_version"), table_name="commercial_billing_config")
    op.drop_table("commercial_billing_config")

    op.drop_index(op.f("ix_bean_pack_visible"), table_name="bean_pack")
    op.drop_index(op.f("ix_bean_pack_enabled"), table_name="bean_pack")
    op.drop_index(op.f("ix_bean_pack_recommended"), table_name="bean_pack")
    op.drop_index(op.f("ix_bean_pack_code"), table_name="bean_pack")
    op.drop_table("bean_pack")

    op.drop_index(op.f("ix_subscription_plan_contact_sales"), table_name="subscription_plan")
    op.drop_index(op.f("ix_subscription_plan_recommended"), table_name="subscription_plan")
    op.drop_index(op.f("ix_subscription_plan_billing_cycle"), table_name="subscription_plan")
    op.drop_column("subscription_plan", "entitlements_json")
    op.drop_column("subscription_plan", "contact_sales")
    op.drop_column("subscription_plan", "recommended")
    op.drop_column("subscription_plan", "beans")
    op.drop_column("subscription_plan", "billing_cycle")
