"""tabel krs

Revision ID: 8b2104krs005
Revises: 3f3403fad0b5
Create Date: 2026-11-17 13:57:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "8b2104krs005"
down_revision: Union[str, Sequence[str], None] = "3f3403fad0b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: buat 4 tabel modul KRS (matakuliah, prerequisite, krs, krs_detail)."""
    op.create_table(
        "matakuliah",
        sa.Column("kode_mk", sa.String(10), primary_key=True),
        sa.Column("nama", sa.String(100), nullable=False),
        sa.Column("sks", sa.Integer(), nullable=False),
        sa.Column("hari", sa.Integer(), nullable=False),
        sa.Column("jam_mulai", sa.Time(), nullable=False),
        sa.Column("jam_selesai", sa.Time(), nullable=False),
        sa.CheckConstraint("sks BETWEEN 1 AND 4", name="ck_matakuliah_sks"),
        sa.CheckConstraint("jam_mulai < jam_selesai", name="ck_matakuliah_jam"),
    )

    op.create_table(
        "prerequisite",
        sa.Column("kode_mk", sa.String(10), sa.ForeignKey("matakuliah.kode_mk"), primary_key=True),
        sa.Column("kode_prasyarat", sa.String(10), sa.ForeignKey("matakuliah.kode_mk"), primary_key=True),
        sa.CheckConstraint("kode_mk <> kode_prasyarat", name="ck_prerequisite_not_self"),
    )

    op.create_table(
        "krs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("nim", sa.String(20), sa.ForeignKey("calon_mahasiswa.nim"), nullable=False, index=True),
        sa.Column("semester", sa.String(5), nullable=False),
        sa.Column(
            "status",
            sa.Enum("DRAFT", "SUBMITTED", "APPROVED", "REVISION", name="krsstatus"),
            nullable=False,
            server_default="DRAFT",
        ),
        sa.Column("dosen_pa_id", sa.Integer(), nullable=True),
        sa.UniqueConstraint("nim", "semester", name="uq_krs_nim_semester"),
    )

    op.create_table(
        "krs_detail",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("krs_id", sa.Integer(), sa.ForeignKey("krs.id"), nullable=False),
        sa.Column("kode_mk", sa.String(10), sa.ForeignKey("matakuliah.kode_mk"), nullable=False),
        sa.Column("nilai", sa.String(2), nullable=True),
        sa.UniqueConstraint("krs_id", "kode_mk", name="uq_krs_detail_mk"),
    )


def downgrade() -> None:
    """Downgrade schema: hapus 4 tabel modul KRS secara berurutan (anak dulu baru induk)."""
    op.drop_table("krs_detail")
    op.drop_table("krs")
    op.drop_table("prerequisite")
    op.drop_table("matakuliah")
