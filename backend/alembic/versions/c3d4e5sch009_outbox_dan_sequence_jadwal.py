"""tambah tabel outbox dan kolom sequence pada jadwal (minggu 8)

Revision ID: c3d4e5sch009
Revises: b2c3d4sch008
Create Date: 2026-11-20 14:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c3d4e5sch009"
down_revision: Union[str, Sequence[str], None] = "b2c3d4sch008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Menambahkan tabel outbox (Transactional Outbox) dan kolom jadwal.sequence (iCalendar)."""
    op.create_table(
        "outbox",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'sent', 'failed')", name="ck_outbox_status"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_outbox_event_id"), "outbox", ["event_id"], unique=True)
    op.create_index(op.f("ix_outbox_status"), "outbox", ["status"], unique=False)

    with op.batch_alter_table("jadwal") as batch_op:
        batch_op.add_column(
            sa.Column("sequence", sa.Integer(), server_default="0", nullable=False)
        )


def downgrade() -> None:
    """Menghapus kolom jadwal.sequence dan tabel outbox."""
    with op.batch_alter_table("jadwal") as batch_op:
        batch_op.drop_column("sequence")

    op.drop_index(op.f("ix_outbox_status"), table_name="outbox")
    op.drop_index(op.f("ix_outbox_event_id"), table_name="outbox")
    op.drop_table("outbox")
