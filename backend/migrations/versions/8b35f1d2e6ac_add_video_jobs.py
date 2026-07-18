"""add_video_jobs

Revision ID: 8b35f1d2e6ac
Revises: dca93ecfbff1
Create Date: 2026-07-18 16:30:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "8b35f1d2e6ac"
down_revision: Union[str, Sequence[str], None] = "dca93ecfbff1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "video_job",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("dry_run", sa.Boolean(), nullable=False),
        sa.Column("params_json", sa.Text(), nullable=False),
        sa.Column("asset_ids_json", sa.Text(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("prompt_version_id", sa.String(length=36), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["prompt_version_id"], ["prompt_version.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_video_job_status"), "video_job", ["status"], unique=False)
    op.create_table(
        "video_item",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("index", sa.Integer(), nullable=False),
        sa.Column("video_type", sa.String(length=120), nullable=False),
        sa.Column("prompt_text", sa.Text(), nullable=False),
        sa.Column("script_markdown", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("provider_id", sa.String(length=36), nullable=True),
        sa.Column("provider_task_id", sa.String(length=160), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("current_version_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["video_job.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["provider_id"], ["provider.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_video_item_job_id"), "video_item", ["job_id"], unique=False)
    op.create_index(op.f("ix_video_item_provider_task_id"), "video_item", ["provider_task_id"], unique=False)
    op.create_index(op.f("ix_video_item_status"), "video_item", ["status"], unique=False)
    op.create_table(
        "video_version",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("item_id", sa.String(length=36), nullable=False),
        sa.Column("parent_version_id", sa.String(length=36), nullable=True),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("instruction", sa.Text(), nullable=False),
        sa.Column("file_path", sa.String(length=1000), nullable=False),
        sa.Column("url", sa.String(length=1000), nullable=False),
        sa.Column("remote_url", sa.String(length=1000), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["item_id"], ["video_item.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_video_version_item_id"), "video_version", ["item_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_video_version_item_id"), table_name="video_version")
    op.drop_table("video_version")
    op.drop_index(op.f("ix_video_item_status"), table_name="video_item")
    op.drop_index(op.f("ix_video_item_provider_task_id"), table_name="video_item")
    op.drop_index(op.f("ix_video_item_job_id"), table_name="video_item")
    op.drop_table("video_item")
    op.drop_index(op.f("ix_video_job_status"), table_name="video_job")
    op.drop_table("video_job")
