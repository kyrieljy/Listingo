"""Wechat Native payment metadata."""
from alembic import op
import sqlalchemy as sa

revision = "f3a4b5c6d7e8"
down_revision = "e2f3a4b5c6d7"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("payment_order", sa.Column("payment_channel", sa.String(20), nullable=True))
    op.add_column("payment_order", sa.Column("wechat_transaction_id", sa.String(64), nullable=True))
    op.create_unique_constraint("uq_payment_order_wechat_transaction", "payment_order", ["wechat_transaction_id"])
    op.add_column("payment_order", sa.Column("code_url", sa.Text(), nullable=True))
    op.add_column("payment_order", sa.Column("payment_error", sa.String(200), nullable=True))
    op.add_column("payment_order", sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("payment_order", sa.Column("refund_reference", sa.String(100), nullable=True))
    op.add_column("payment_order", sa.Column("refund_note", sa.Text(), nullable=True))


def downgrade():
    op.drop_constraint("uq_payment_order_wechat_transaction", "payment_order", type_="unique")
    for column in ("refund_note", "refund_reference", "last_checked_at", "payment_error", "code_url", "wechat_transaction_id", "payment_channel"):
        op.drop_column("payment_order", column)
