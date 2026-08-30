"""add task-completion notify channels (feishu webhook + sms notify template)

Revision ID: d1e2f3a4b5c6
Revises: c0a1b2c3d4e5
Create Date: 2026-08-30 18:00:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "d1e2f3a4b5c6"
down_revision: Union[str, Sequence[str], None] = "c0a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # User-configured Feishu custom-bot webhook; posted to when a task completes.
    # No format validation (per product decision); empty string means "not configured".
    op.add_column(
        "app_user",
        sa.Column("feishu_webhook", sa.String(length=512), nullable=False, server_default=""),
    )
    # Backend Aliyun SMS template used for task-completion notifications; kept
    # separate from the verification-code templates and quota.
    op.add_column(
        "sms_config",
        sa.Column("notify_template_code", sa.String(length=80), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("sms_config", "notify_template_code")
    op.drop_column("app_user", "feishu_webhook")
