"""Link website WeChat identities to existing Listingo accounts."""
import sqlalchemy as sa
from alembic import op

revision = "1a2b3c4d5e6f"
down_revision = "f3a4b5c6d7e8"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "wechat_identity",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("app_id", sa.String(64), nullable=False),
        sa.Column("openid", sa.String(128), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("app_id", "openid", name="uq_wechat_identity_openid"),
        sa.UniqueConstraint("app_id", "user_id", name="uq_wechat_identity_user"),
    )
    op.create_index("ix_wechat_identity_user_id", "wechat_identity", ["user_id"])


def downgrade():
    op.drop_table("wechat_identity")
