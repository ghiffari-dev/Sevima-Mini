"""tambah tabel attendance_session dan attendance_record untuk modul presensi QR (minggu 12)

Revision ID: f6g7h8att012
Revises: e5f6g7fin011
Create Date: 2026-11-20 17:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f6g7h8att012"
down_revision: Union[str, Sequence[str], None] = "e5f6g7fin011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Membuat tabel attendance_session dan attendance_record."""
    op.create_table(
        "attendance_session",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("jadwal_id", sa.Integer(), nullable=True),
        sa.Column("kelas_id", sa.Integer(), nullable=False),
        sa.Column("dosen_id", sa.Integer(), nullable=False),
        sa.Column("tanggal", sa.Date(), nullable=False),
        sa.Column("pertemuan_ke", sa.Integer(), nullable=False),
        sa.Column("hari", sa.Integer(), nullable=False),
        sa.Column("jam_mulai", sa.Time(), nullable=False),
        sa.Column("jam_selesai", sa.Time(), nullable=False),
        sa.Column("ruangan_kode", sa.String(length=20), nullable=True),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("secret", sa.String(length=64), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closes_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("radius_m", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "status IN ('open', 'closed')", name="ck_attendance_session_status"
        ),
        sa.CheckConstraint(
            "hari BETWEEN 1 AND 6", name="ck_attendance_session_hari"
        ),
        sa.CheckConstraint(
            "pertemuan_ke >= 1", name="ck_attendance_session_pertemuan"
        ),
        sa.ForeignKeyConstraint(["dosen_id"], ["dosen.id"]),
        sa.ForeignKeyConstraint(
            ["jadwal_id"], ["jadwal.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["kelas_id"], ["kelas.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "kelas_id",
            "tanggal",
            "jam_mulai",
            name="uq_attendance_session_kelas_slot",
        ),
        sa.UniqueConstraint(
            "kelas_id",
            "pertemuan_ke",
            name="uq_attendance_session_kelas_pertemuan",
        ),
    )
    op.create_index(
        op.f("ix_attendance_session_jadwal_id"),
        "attendance_session",
        ["jadwal_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_attendance_session_kelas_id"),
        "attendance_session",
        ["kelas_id"],
        unique=False,
    )
    op.create_index(
        "ix_attendance_session_kelas_tanggal",
        "attendance_session",
        ["kelas_id", "tanggal"],
        unique=False,
    )

    op.create_table(
        "attendance_record",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("nim", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("scanned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("qr_window", sa.Integer(), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("accuracy_m", sa.Float(), nullable=True),
        sa.Column("distance_m", sa.Float(), nullable=True),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.CheckConstraint(
            "status IN ('hadir', 'terlambat')",
            name="ck_attendance_record_status",
        ),
        sa.ForeignKeyConstraint(["nim"], ["calon_mahasiswa.nim"]),
        sa.ForeignKeyConstraint(
            ["session_id"], ["attendance_session.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "session_id", "nim", name="uq_attendance_record_session_nim"
        ),
    )
    op.create_index(
        op.f("ix_attendance_record_nim"),
        "attendance_record",
        ["nim"],
        unique=False,
    )
    op.create_index(
        op.f("ix_attendance_record_session_id"),
        "attendance_record",
        ["session_id"],
        unique=False,
    )


def downgrade() -> None:
    """Menghapus tabel attendance_record dan attendance_session."""
    op.drop_index(
        op.f("ix_attendance_record_session_id"),
        table_name="attendance_record",
    )
    op.drop_index(
        op.f("ix_attendance_record_nim"),
        table_name="attendance_record",
    )
    op.drop_table("attendance_record")

    op.drop_index(
        "ix_attendance_session_kelas_tanggal",
        table_name="attendance_session",
    )
    op.drop_index(
        op.f("ix_attendance_session_kelas_id"),
        table_name="attendance_session",
    )
    op.drop_index(
        op.f("ix_attendance_session_jadwal_id"),
        table_name="attendance_session",
    )
    op.drop_table("attendance_session")
