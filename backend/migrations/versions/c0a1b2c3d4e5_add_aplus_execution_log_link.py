"""add aplus job link to execution log

Revision ID: c0a1b2c3d4e5
Revises: b9f4d2a6c7e8
Create Date: 2026-08-30 15:30:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "c0a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "b9f4d2a6c7e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # execution_log is the shared audit table for generation jobs. APlus plan
    # jobs also record image-safety blocks there, but their ids live in
    # aplus_job, not generation_job. Add a dedicated nullable link so the
    # existing generation_job FK stays intact while APlus jobs can log too.
    op.add_column(
        "execution_log",
        sa.Column(
            "aplus_job_id",
            sa.String(length=36),
            sa.ForeignKey("aplus_job.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.create_index(
        op.f("ix_execution_log_aplus_job_id"), "execution_log", ["aplus_job_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_execution_log_aplus_job_id"), table_name="execution_log")
    op.drop_column("execution_log", "aplus_job_id")
