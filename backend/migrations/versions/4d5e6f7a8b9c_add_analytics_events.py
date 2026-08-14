"""add_analytics_events

Revision ID: 4d5e6f7a8b9c
Revises: 3c4d5e6f7a8b
Create Date: 2026-08-13 01:20:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "4d5e6f7a8b9c"
down_revision: Union[str, Sequence[str], None] = "3c4d5e6f7a8b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "analytics_event",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column("session_id", sa.String(length=80), nullable=False),
        sa.Column("event_name", sa.String(length=120), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("surface", sa.String(length=80), nullable=False),
        sa.Column("business_type", sa.String(length=40), nullable=False),
        sa.Column("feature_key", sa.String(length=80), nullable=False),
        sa.Column("platform", sa.String(length=80), nullable=False),
        sa.Column("market", sa.String(length=80), nullable=False),
        sa.Column("language", sa.String(length=80), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("ip_address", sa.String(length=80), nullable=False),
        sa.Column("user_agent", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_analytics_event_user_id"), "analytics_event", ["user_id"], unique=False)
    op.create_index(op.f("ix_analytics_event_event_name"), "analytics_event", ["event_name"], unique=False)
    op.create_index(op.f("ix_analytics_event_event_type"), "analytics_event", ["event_type"], unique=False)
    op.create_index(op.f("ix_analytics_event_surface"), "analytics_event", ["surface"], unique=False)
    op.create_index(op.f("ix_analytics_event_business_type"), "analytics_event", ["business_type"], unique=False)
    op.create_index(op.f("ix_analytics_event_feature_key"), "analytics_event", ["feature_key"], unique=False)
    op.create_index(op.f("ix_analytics_event_platform"), "analytics_event", ["platform"], unique=False)
    op.create_index(op.f("ix_analytics_event_created_at"), "analytics_event", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_analytics_event_created_at"), table_name="analytics_event")
    op.drop_index(op.f("ix_analytics_event_platform"), table_name="analytics_event")
    op.drop_index(op.f("ix_analytics_event_feature_key"), table_name="analytics_event")
    op.drop_index(op.f("ix_analytics_event_business_type"), table_name="analytics_event")
    op.drop_index(op.f("ix_analytics_event_surface"), table_name="analytics_event")
    op.drop_index(op.f("ix_analytics_event_event_type"), table_name="analytics_event")
    op.drop_index(op.f("ix_analytics_event_event_name"), table_name="analytics_event")
    op.drop_index(op.f("ix_analytics_event_user_id"), table_name="analytics_event")
    op.drop_table("analytics_event")
