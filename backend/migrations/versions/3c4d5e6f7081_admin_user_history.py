"""Add admin user notes and copywriting history."""

from alembic import op
import sqlalchemy as sa

revision = "3c4d5e6f7081"
down_revision = "2b3c4d5e6f70"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("app_user", sa.Column("admin_note", sa.String(1000), nullable=False, server_default=""))
    op.create_table(
        "copywriting_record",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("original_input", sa.Text(), nullable=False),
        sa.Column("rewritten_text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_copywriting_record_user_id", "copywriting_record", ["user_id"])


def downgrade():
    op.drop_table("copywriting_record")
    op.drop_column("app_user", "admin_note")
