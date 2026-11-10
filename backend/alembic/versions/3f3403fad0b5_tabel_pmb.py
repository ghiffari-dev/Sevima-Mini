"""tabel pmb

Revision ID: 3f3403fad0b5
Revises: 
Create Date: 2026-11-10 14:29:39.534943

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3f3403fad0b5'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "program_studi",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("kode", sa.String(3), nullable=False, unique=True),
        sa.Column("nama", sa.String(100), nullable=False),
        sa.Column("fakultas", sa.String(100), nullable=False)
    )
    op.create_table(
        "jalur_masuk",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("nama", sa.String(50), nullable=False, unique=True)
    )
    op.create_table(
        "calon_mahasiswa",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("nama_lengkap", sa.String(150), nullable=False),
        sa.Column("email", sa.String(150), nullable=False, unique=True),
        sa.Column("phone", sa.String(20), nullable=False),
        sa.Column("tanggal_lahir", sa.Date(), nullable=False),
        sa.Column("alamat", sa.Text(), nullable=True),
        sa.Column("program_studi_id", sa.Integer(), sa.ForeignKey("program_studi.id"), nullable=False),
        sa.Column("jalur_masuk_id", sa.Integer(), sa.ForeignKey("jalur_masuk.id"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default='pending'),
        sa.Column("nim", sa.String(20), unique=True, nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("approved_at", sa.DateTime(), nullable=True)
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("calon_mahasiswa") # anak dulu
    op.drop_table("jalur_masuk")
    op.drop_table("program_studi") # induk terakhir

