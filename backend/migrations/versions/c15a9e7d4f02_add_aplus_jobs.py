"""add_aplus_jobs

Revision ID: c15a9e7d4f02
Revises: 8b35f1d2e6ac
Create Date: 2026-07-22 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c15a9e7d4f02"
down_revision: Union[str, Sequence[str], None] = "8b35f1d2e6ac"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "aplus_job",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("job_type", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("dry_run", sa.Boolean(), nullable=False),
        sa.Column("params_json", sa.Text(), nullable=False),
        sa.Column("asset_ids_json", sa.Text(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("prompt_version_id", sa.String(length=36), nullable=False),
        sa.Column("source_plan_job_id", sa.String(length=36), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["prompt_version_id"], ["prompt_version.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_aplus_job_job_type"), "aplus_job", ["job_type"], unique=False)
    op.create_index(op.f("ix_aplus_job_source_plan_job_id"), "aplus_job", ["source_plan_job_id"], unique=False)
    op.create_index(op.f("ix_aplus_job_status"), "aplus_job", ["status"], unique=False)
    op.create_table(
        "aplus_item",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("index", sa.Integer(), nullable=False),
        sa.Column("module_index", sa.Integer(), nullable=False),
        sa.Column("module_name", sa.String(length=160), nullable=False),
        sa.Column("output_mode", sa.String(length=60), nullable=False),
        sa.Column("aspect_ratio", sa.String(length=40), nullable=False),
        sa.Column("image_prompt", sa.Text(), nullable=False),
        sa.Column("copy_requirements", sa.Text(), nullable=False),
        sa.Column("prompt_text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("provider_id", sa.String(length=36), nullable=True),
        sa.Column("source_web_item_id", sa.String(length=36), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("current_version_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["aplus_job.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["provider_id"], ["provider.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_aplus_item_job_id"), "aplus_item", ["job_id"], unique=False)
    op.create_index(op.f("ix_aplus_item_source_web_item_id"), "aplus_item", ["source_web_item_id"], unique=False)
    op.create_index(op.f("ix_aplus_item_status"), "aplus_item", ["status"], unique=False)
    op.create_table(
        "aplus_version",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("item_id", sa.String(length=36), nullable=False),
        sa.Column("parent_version_id", sa.String(length=36), nullable=True),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("instruction", sa.Text(), nullable=False),
        sa.Column("file_path", sa.String(length=1000), nullable=False),
        sa.Column("url", sa.String(length=1000), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["item_id"], ["aplus_item.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_aplus_version_item_id"), "aplus_version", ["item_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_aplus_version_item_id"), table_name="aplus_version")
    op.drop_table("aplus_version")
    op.drop_index(op.f("ix_aplus_item_status"), table_name="aplus_item")
    op.drop_index(op.f("ix_aplus_item_source_web_item_id"), table_name="aplus_item")
    op.drop_index(op.f("ix_aplus_item_job_id"), table_name="aplus_item")
    op.drop_table("aplus_item")
    op.drop_index(op.f("ix_aplus_job_status"), table_name="aplus_job")
    op.drop_index(op.f("ix_aplus_job_source_plan_job_id"), table_name="aplus_job")
    op.drop_index(op.f("ix_aplus_job_job_type"), table_name="aplus_job")
    op.drop_table("aplus_job")
