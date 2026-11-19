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
    """Upgrade schema: tambah kolom state/locking pada krs serta tabel krs_log dan notifikasi."""
    with op.batch_alter_table("krs") as batch_op:
        batch_op.add_column(sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("catatan_revisi", sa.String(500), nullable=True))
        batch_op.add_column(
            sa.Column("version", sa.Integer(), server_default="1", nullable=False)
        )
        batch_op.add_column(sa.Column("diubah_pada", sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        "krs_log",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("krs_id", sa.Integer(), nullable=False),
        sa.Column("aksi", sa.String(length=50), nullable=False),
        sa.Column("oleh", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["krs_id"], ["krs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_krs_log_krs_id"), "krs_log", ["krs_id"], unique=False)

    op.create_table(
        "notifikasi",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("nim", sa.String(length=20), nullable=False),
        sa.Column("pesan", sa.String(length=500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["nim"], ["calon_mahasiswa.nim"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_notifikasi_nim"), "notifikasi", ["nim"], unique=False)


def downgrade() -> None:
    """Downgrade schema: hapus tabel notifikasi, krs_log, dan kolom tambahan dari tabel krs."""
    op.drop_index(op.f("ix_notifikasi_nim"), table_name="notifikasi")
    op.drop_table("notifikasi")
    op.drop_index(op.f("ix_krs_log_krs_id"), table_name="krs_log")
    op.drop_table("krs_log")

    with op.batch_alter_table("krs") as batch_op:
        batch_op.drop_column("diubah_pada")
        batch_op.drop_column("version")
        batch_op.drop_column("catatan_revisi")
        batch_op.drop_column("approved_at")
        batch_op.drop_column("submitted_at")
