"""tabel jadwal dan ruangan

Revision ID: a1b2c3sch007
Revises: 9c3205krs006
Create Date: 2026-11-19 17:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a1b2c3sch007"
down_revision: Union[str, Sequence[str], None] = "9c3205krs006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: buat tabel ruangan dan jadwal_kuliah untuk Minggu 7-8."""
    op.create_table(
        "ruangan",
        sa.Column("kode_ruangan", sa.String(length=20), nullable=False),
        sa.Column("nama", sa.String(length=100), nullable=False),
        sa.Column("kapasitas", sa.Integer(), nullable=False),
        sa.Column("gedung", sa.String(length=50), nullable=True),
        sa.CheckConstraint("kapasitas > 0", name="ck_ruangan_kapasitas"),
        sa.PrimaryKeyConstraint("kode_ruangan"),
    )

    op.create_table(
        "jadwal_kuliah",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("kode_mk", sa.String(length=10), nullable=False),
        sa.Column("ruangan_kode", sa.String(length=20), nullable=False),
        sa.Column("dosen", sa.String(length=120), nullable=False),
        sa.Column("semester", sa.String(length=10), server_default="20251", nullable=False),
        sa.Column("hari", sa.Integer(), nullable=False),
        sa.Column("jam_mulai", sa.Time(), nullable=False),
        sa.Column("jam_selesai", sa.Time(), nullable=False),
        sa.Column("enrolled_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("hari BETWEEN 1 AND 6", name="ck_jadwal_hari"),
        sa.CheckConstraint("jam_mulai < jam_selesai", name="ck_jadwal_jam"),
        sa.CheckConstraint("enrolled_count >= 0", name="ck_jadwal_enrolled"),
        sa.ForeignKeyConstraint(["kode_mk"], ["matakuliah.kode_mk"]),
        sa.ForeignKeyConstraint(["ruangan_kode"], ["ruangan.kode_ruangan"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_jadwal_kuliah_kode_mk"), "jadwal_kuliah", ["kode_mk"], unique=False
    )
    op.create_index(
        op.f("ix_jadwal_kuliah_ruangan_kode"),
        "jadwal_kuliah",
        ["ruangan_kode"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema: hapus tabel jadwal_kuliah dan ruangan."""
    op.drop_index(op.f("ix_jadwal_kuliah_ruangan_kode"), table_name="jadwal_kuliah")
    op.drop_index(op.f("ix_jadwal_kuliah_kode_mk"), table_name="jadwal_kuliah")
    op.drop_table("jadwal_kuliah")
    op.drop_table("ruangan")
