"""align schema for PostgreSQL

Revision ID: a7c4e9f21b68
Revises: 5f6a7b8c9d0e
Create Date: 2026-08-23 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op


revision: str = "a7c4e9f21b68"
down_revision: Union[str, Sequence[str], None] = "5f6a7b8c9d0e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(op.f("ix_analytics_event_session_id"), "analytics_event", ["session_id"], unique=False)
    op.create_index(op.f("ix_analytics_event_market"), "analytics_event", ["market"], unique=False)
    op.create_index(op.f("ix_analytics_event_language"), "analytics_event", ["language"], unique=False)
    op.create_foreign_key("fk_generation_job_user_id_app_user", "generation_job", "app_user", ["user_id"], ["id"])
    op.create_foreign_key("fk_video_job_user_id_app_user", "video_job", "app_user", ["user_id"], ["id"])
    op.create_foreign_key("fk_aplus_job_user_id_app_user", "aplus_job", "app_user", ["user_id"], ["id"])
    op.create_foreign_key("fk_asset_user_id_app_user", "asset", "app_user", ["user_id"], ["id"])
    op.create_foreign_key("fk_batch_job_user_id_app_user", "batch_job", "app_user", ["user_id"], ["id"])


def downgrade() -> None:
    op.drop_constraint("fk_batch_job_user_id_app_user", "batch_job", type_="foreignkey")
    op.drop_constraint("fk_asset_user_id_app_user", "asset", type_="foreignkey")
    op.drop_constraint("fk_aplus_job_user_id_app_user", "aplus_job", type_="foreignkey")
    op.drop_constraint("fk_video_job_user_id_app_user", "video_job", type_="foreignkey")
    op.drop_constraint("fk_generation_job_user_id_app_user", "generation_job", type_="foreignkey")
    op.drop_index(op.f("ix_analytics_event_language"), table_name="analytics_event")
    op.drop_index(op.f("ix_analytics_event_market"), table_name="analytics_event")
    op.drop_index(op.f("ix_analytics_event_session_id"), table_name="analytics_event")
