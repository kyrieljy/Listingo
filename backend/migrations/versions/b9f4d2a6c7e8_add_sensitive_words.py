"""add sensitive words

Revision ID: b9f4d2a6c7e8
Revises: a7c4e9f21b68
Create Date: 2026-08-30 00:00:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "b9f4d2a6c7e8"
down_revision: Union[str, Sequence[str], None] = "a7c4e9f21b68"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sensitive_word_config",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("max_variants_per_word", sa.Integer(), nullable=False),
        sa.Column("max_total_variants", sa.Integer(), nullable=False),
        sa.Column("max_snapshot_bytes", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_sensitive_word_config_enabled"), "sensitive_word_config", ["enabled"], unique=False)
    op.create_table(
        "sensitive_word",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("term", sa.String(length=120), nullable=False),
        sa.Column("normalized_term", sa.String(length=120), nullable=False),
        sa.Column("aliases_json", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("normalized_term", name="uq_sensitive_word_normalized_term"),
    )
    op.create_index(op.f("ix_sensitive_word_enabled"), "sensitive_word", ["enabled"], unique=False)
    op.create_index(op.f("ix_sensitive_word_normalized_term"), "sensitive_word", ["normalized_term"], unique=False)
    op.create_table(
        "sensitive_word_snapshot",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("source_digest", sa.String(length=64), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("word_count", sa.Integer(), nullable=False),
        sa.Column("variant_count", sa.Integer(), nullable=False),
        sa.Column("payload_bytes", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_digest", name="uq_sensitive_word_snapshot_source_digest"),
    )
    op.create_index(op.f("ix_sensitive_word_snapshot_source_digest"), "sensitive_word_snapshot", ["source_digest"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_sensitive_word_snapshot_source_digest"), table_name="sensitive_word_snapshot")
    op.drop_table("sensitive_word_snapshot")
    op.drop_index(op.f("ix_sensitive_word_normalized_term"), table_name="sensitive_word")
    op.drop_index(op.f("ix_sensitive_word_enabled"), table_name="sensitive_word")
    op.drop_table("sensitive_word")
    op.drop_index(op.f("ix_sensitive_word_config_enabled"), table_name="sensitive_word_config")
    op.drop_table("sensitive_word_config")
