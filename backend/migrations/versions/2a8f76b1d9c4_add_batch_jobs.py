"""add_batch_jobs

Revision ID: 2a8f76b1d9c4
Revises: b7d2c6a9e8f1
Create Date: 2026-08-09 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "2a8f76b1d9c4"
down_revision: Union[str, Sequence[str], None] = "b7d2c6a9e8f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("generation_item", sa.Column("provider_task_id", sa.String(length=160), nullable=True))
    op.create_index(op.f("ix_generation_item_provider_task_id"), "generation_item", ["provider_task_id"], unique=False)
    op.add_column("aplus_item", sa.Column("provider_task_id", sa.String(length=160), nullable=True))
    op.create_index(op.f("ix_aplus_item_provider_task_id"), "aplus_item", ["provider_task_id"], unique=False)
    op.create_table(
        "batch_job",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("business_type", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("global_params_json", sa.Text(), nullable=False),
        sa.Column("total_count", sa.Integer(), nullable=False),
        sa.Column("completed_count", sa.Integer(), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("notification_config_json", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_batch_job_business_type"), "batch_job", ["business_type"], unique=False)
    op.create_index(op.f("ix_batch_job_status"), "batch_job", ["status"], unique=False)
    op.create_table(
        "batch_item",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("batch_job_id", sa.String(length=36), nullable=False),
        sa.Column("index", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("params_json", sa.Text(), nullable=False),
        sa.Column("asset_ids_json", sa.Text(), nullable=False),
        sa.Column("generation_job_id", sa.String(length=36), nullable=True),
        sa.Column("aplus_plan_job_id", sa.String(length=36), nullable=True),
        sa.Column("aplus_generation_job_id", sa.String(length=36), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["batch_job_id"], ["batch_job.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_batch_item_batch_job_id"), "batch_item", ["batch_job_id"], unique=False)
    op.create_index(op.f("ix_batch_item_status"), "batch_item", ["status"], unique=False)
    op.create_index(op.f("ix_batch_item_generation_job_id"), "batch_item", ["generation_job_id"], unique=False)
    op.create_index(op.f("ix_batch_item_aplus_plan_job_id"), "batch_item", ["aplus_plan_job_id"], unique=False)
    op.create_index(op.f("ix_batch_item_aplus_generation_job_id"), "batch_item", ["aplus_generation_job_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_batch_item_aplus_generation_job_id"), table_name="batch_item")
    op.drop_index(op.f("ix_batch_item_aplus_plan_job_id"), table_name="batch_item")
    op.drop_index(op.f("ix_batch_item_generation_job_id"), table_name="batch_item")
    op.drop_index(op.f("ix_batch_item_status"), table_name="batch_item")
    op.drop_index(op.f("ix_batch_item_batch_job_id"), table_name="batch_item")
    op.drop_table("batch_item")
    op.drop_index(op.f("ix_batch_job_status"), table_name="batch_job")
    op.drop_index(op.f("ix_batch_job_business_type"), table_name="batch_job")
    op.drop_table("batch_job")
    op.drop_index(op.f("ix_aplus_item_provider_task_id"), table_name="aplus_item")
    op.drop_column("aplus_item", "provider_task_id")
    op.drop_index(op.f("ix_generation_item_provider_task_id"), table_name="generation_item")
    op.drop_column("generation_item", "provider_task_id")
