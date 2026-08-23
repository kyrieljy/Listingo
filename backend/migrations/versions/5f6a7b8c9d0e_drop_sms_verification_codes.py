"""drop sms verification codes

Revision ID: 5f6a7b8c9d0e
Revises: 4d5e6f7a8b9c
Create Date: 2026-08-23 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "5f6a7b8c9d0e"
down_revision: Union[str, Sequence[str], None] = "4d5e6f7a8b9c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index(op.f("ix_sms_verification_code_phone"), table_name="sms_verification_code")
    op.drop_index(op.f("ix_sms_verification_code_purpose"), table_name="sms_verification_code")
    op.drop_index(op.f("ix_sms_verification_code_expires_at"), table_name="sms_verification_code")
    op.drop_table("sms_verification_code")


def downgrade() -> None:
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
