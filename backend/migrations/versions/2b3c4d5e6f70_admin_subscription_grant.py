"""Record the administrator who granted a subscription."""
import sqlalchemy as sa
from alembic import op

revision = "2b3c4d5e6f70"
down_revision = "1a2b3c4d5e6f"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("user_subscription", sa.Column("admin_granted_by", sa.String(36), nullable=True))


def downgrade():
    op.drop_column("user_subscription", "admin_granted_by")
