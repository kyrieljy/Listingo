"""add_prompt_test_runs

Revision ID: b7d2c6a9e8f1
Revises: c15a9e7d4f02
Create Date: 2026-07-29 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b7d2c6a9e8f1"
down_revision: Union[str, Sequence[str], None] = "c15a9e7d4f02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("generation_job", sa.Column("is_admin_test", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("video_job", sa.Column("is_admin_test", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("aplus_job", sa.Column("is_admin_test", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_index(op.f("ix_generation_job_is_admin_test"), "generation_job", ["is_admin_test"], unique=False)
    op.create_index(op.f("ix_video_job_is_admin_test"), "video_job", ["is_admin_test"], unique=False)
    op.create_index(op.f("ix_aplus_job_is_admin_test"), "aplus_job", ["is_admin_test"], unique=False)
    op.create_table(
        "prompt_test_run",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("prompt_id", sa.String(length=36), nullable=False),
        sa.Column("prompt_code", sa.String(length=80), nullable=False),
        sa.Column("test_type", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("prompt_content_snapshot", sa.Text(), nullable=False),
        sa.Column("prompt_content_sha256", sa.String(length=64), nullable=False),
        sa.Column("input_params_json", sa.Text(), nullable=False),
        sa.Column("raw_output", sa.Text(), nullable=False),
        sa.Column("parsed_output_json", sa.Text(), nullable=False),
        sa.Column("validation_errors_json", sa.Text(), nullable=False),
        sa.Column("related_job_type", sa.String(length=40), nullable=True),
        sa.Column("related_job_id", sa.String(length=36), nullable=True),
        sa.Column("artifact_urls_json", sa.Text(), nullable=False),
        sa.Column("provider_code", sa.String(length=80), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["prompt_id"], ["prompt.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_prompt_test_run_prompt_id"), "prompt_test_run", ["prompt_id"], unique=False)
    op.create_index(op.f("ix_prompt_test_run_prompt_code"), "prompt_test_run", ["prompt_code"], unique=False)
    op.create_index(op.f("ix_prompt_test_run_test_type"), "prompt_test_run", ["test_type"], unique=False)
    op.create_index(op.f("ix_prompt_test_run_status"), "prompt_test_run", ["status"], unique=False)
    op.create_index(op.f("ix_prompt_test_run_related_job_id"), "prompt_test_run", ["related_job_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_prompt_test_run_related_job_id"), table_name="prompt_test_run")
    op.drop_index(op.f("ix_prompt_test_run_status"), table_name="prompt_test_run")
    op.drop_index(op.f("ix_prompt_test_run_test_type"), table_name="prompt_test_run")
    op.drop_index(op.f("ix_prompt_test_run_prompt_code"), table_name="prompt_test_run")
    op.drop_index(op.f("ix_prompt_test_run_prompt_id"), table_name="prompt_test_run")
    op.drop_table("prompt_test_run")
    op.drop_index(op.f("ix_aplus_job_is_admin_test"), table_name="aplus_job")
    op.drop_index(op.f("ix_video_job_is_admin_test"), table_name="video_job")
    op.drop_index(op.f("ix_generation_job_is_admin_test"), table_name="generation_job")
    op.drop_column("aplus_job", "is_admin_test")
    op.drop_column("video_job", "is_admin_test")
    op.drop_column("generation_job", "is_admin_test")
