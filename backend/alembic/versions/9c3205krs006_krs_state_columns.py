"""add approved_at and catatan_revisi to krs

Revision ID: 9c3205krs006
Revises: 8b2104krs005
Create Date: 2026-11-19 12:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "9c3205krs006"
down_revision: Union[str, Sequence[str], None] = "8b2104krs005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: tambah kolom approved_at dan catatan_revisi pada tabel krs."""
    with op.batch_alter_table("krs") as batch_op:
        batch_op.add_column(sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("catatan_revisi", sa.String(500), nullable=True))


def downgrade() -> None:
    """Downgrade schema: hapus kolom catatan_revisi dan approved_at dari tabel krs."""
    with op.batch_alter_table("krs") as batch_op:
        batch_op.drop_column("catatan_revisi")
        batch_op.drop_column("approved_at")
