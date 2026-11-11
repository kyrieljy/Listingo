"""Remember account acknowledgement for watermark-free downloads."""

import sqlalchemy as sa
from alembic import op

revision = "4d5e6f708192"
down_revision = "3c4d5e6f7081"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "app_user",
        sa.Column("watermark_acknowledged", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade():
    op.drop_column("app_user", "watermark_acknowledged")
