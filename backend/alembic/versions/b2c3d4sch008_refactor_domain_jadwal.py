"""refactor domain jadwal ke 4 model (ruangan, dosen, kelas, jadwal) dan relasi krs_detail

Revision ID: b2c3d4sch008
Revises: a1b2c3sch007
Create Date: 2026-11-20 13:40:00.000000

"""
from datetime import time
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b2c3d4sch008"
down_revision: Union[str, Sequence[str], None] = "a1b2c3sch007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: migrasi ke Ruangan(kode), Dosen, Kelas, Jadwal + hapus hari/jam di matakuliah."""
    bind = op.get_bind()

    existing_rooms = bind.execute(
        sa.text("SELECT kode_ruangan, nama, kapasitas, gedung FROM ruangan")
    ).fetchall()
    existing_schedules = bind.execute(
        sa.text(
            "SELECT kode_mk, ruangan_kode, dosen, semester, hari, jam_mulai, jam_selesai, created_at, updated_at "
            "FROM jadwal_kuliah"
        )
    ).fetchall()

    op.drop_index(op.f("ix_jadwal_kuliah_ruangan_kode"), table_name="jadwal_kuliah")
    op.drop_index(op.f("ix_jadwal_kuliah_kode_mk"), table_name="jadwal_kuliah")
    op.drop_table("jadwal_kuliah")
    op.drop_table("ruangan")

    op.create_table(
        "ruangan",
        sa.Column("kode", sa.String(length=20), nullable=False),
        sa.Column("nama", sa.String(length=100), server_default="", nullable=False),
        sa.Column("kapasitas", sa.Integer(), nullable=False),
        sa.Column("gedung", sa.String(length=50), nullable=True),
        sa.CheckConstraint("kapasitas > 0", name="ck_ruangan_kapasitas"),
        sa.PrimaryKeyConstraint("kode"),
    )

    for kode_r, nama_r, kap_r, gedung_r in existing_rooms:
        bind.execute(
            sa.text(
                "INSERT INTO ruangan (kode, nama, kapasitas, gedung) VALUES (:kode, :nama, :kapasitas, :gedung)"
            ),
            {"kode": kode_r, "nama": nama_r, "kapasitas": kap_r, "gedung": gedung_r},
        )

    op.create_table(
        "dosen",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("nidn", sa.String(length=20), nullable=False),
        sa.Column("nama", sa.String(length=120), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_dosen_nidn"), "dosen", ["nidn"], unique=True)

    op.create_table(
        "kelas",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("kode_mk", sa.String(length=10), nullable=False),
        sa.Column("nama_kelas", sa.String(length=20), nullable=False),
        sa.Column("kuota", sa.Integer(), server_default="40", nullable=False),
        sa.Column("semester", sa.String(length=10), server_default="20251", nullable=False),
        sa.CheckConstraint("kuota > 0", name="ck_kelas_kuota"),
        sa.ForeignKeyConstraint(["kode_mk"], ["matakuliah.kode_mk"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("kode_mk", "nama_kelas", "semester", name="uq_kelas_mk_nama_semester"),
    )
    op.create_index(op.f("ix_kelas_kode_mk"), "kelas", ["kode_mk"], unique=False)

    op.create_table(
        "jadwal",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("kelas_id", sa.Integer(), nullable=False),
        sa.Column("ruangan_kode", sa.String(length=20), nullable=False),
        sa.Column("dosen_id", sa.Integer(), nullable=False),
        sa.Column("hari", sa.Integer(), nullable=False),
        sa.Column("jam_mulai", sa.Time(), nullable=False),
        sa.Column("jam_selesai", sa.Time(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("hari BETWEEN 1 AND 6", name="ck_jadwal_hari"),
        sa.CheckConstraint("jam_mulai < jam_selesai", name="ck_jadwal_jam"),
        sa.ForeignKeyConstraint(["dosen_id"], ["dosen.id"]),
        sa.ForeignKeyConstraint(["kelas_id"], ["kelas.id"]),
        sa.ForeignKeyConstraint(["ruangan_kode"], ["ruangan.kode"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_jadwal_kelas_id"), "jadwal", ["kelas_id"], unique=False)
    op.create_index("ix_jadwal_hari_ruangan", "jadwal", ["hari", "ruangan_kode"], unique=False)
    op.create_index("ix_jadwal_hari_dosen", "jadwal", ["hari", "dosen_id"], unique=False)

    # Migrasikan jadwal_kuliah existing (bila ada) ke dosen + kelas + jadwal
    if existing_schedules:
        dosen_map: dict[str, int] = {}
        kelas_map: dict[tuple[str, str], int] = {}
        for kode_mk, r_kode, dosen_nama, sem, hari, j_mulai, j_selesai, c_at, u_at in existing_schedules:
            if dosen_nama not in dosen_map:
                nidn = f"MIG-{len(dosen_map) + 1:04d}"
                bind.execute(
                    sa.text("INSERT INTO dosen (nidn, nama) VALUES (:nidn, :nama)"),
                    {"nidn": nidn, "nama": dosen_nama},
                )
                d_id = bind.execute(
                    sa.text("SELECT id FROM dosen WHERE nidn = :nidn"),
                    {"nidn": nidn},
                ).scalar_one()
                dosen_map[dosen_nama] = int(d_id)

            k_key = (kode_mk, sem)
            if k_key not in kelas_map:
                bind.execute(
                    sa.text(
                        "INSERT INTO kelas (kode_mk, nama_kelas, kuota, semester) "
                        "VALUES (:kode_mk, 'A', 40, :semester)"
                    ),
                    {"kode_mk": kode_mk, "semester": sem},
                )
                k_id = bind.execute(
                    sa.text(
                        "SELECT id FROM kelas WHERE kode_mk = :kode_mk AND nama_kelas = 'A' AND semester = :semester"
                    ),
                    {"kode_mk": kode_mk, "semester": sem},
                ).scalar_one()
                kelas_map[k_key] = int(k_id)

            bind.execute(
                sa.text(
                    "INSERT INTO jadwal (kelas_id, ruangan_kode, dosen_id, hari, jam_mulai, jam_selesai, created_at, updated_at) "
                    "VALUES (:kelas_id, :ruangan_kode, :dosen_id, :hari, :jam_mulai, :jam_selesai, :created_at, :updated_at)"
                ),
                {
                    "kelas_id": kelas_map[k_key],
                    "ruangan_kode": r_kode,
                    "dosen_id": dosen_map[dosen_nama],
                    "hari": hari,
                    "jam_mulai": j_mulai,
                    "jam_selesai": j_selesai,
                    "created_at": c_at,
                    "updated_at": u_at,
                },
            )

    with op.batch_alter_table("matakuliah", recreate="always") as batch_op:
        batch_op.drop_constraint("ck_matakuliah_jam", type_="check")
        batch_op.drop_column("hari")
        batch_op.drop_column("jam_mulai")
        batch_op.drop_column("jam_selesai")

    with op.batch_alter_table("krs_detail") as batch_op:
        batch_op.add_column(sa.Column("kelas_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_krs_detail_kelas_id", "kelas", ["kelas_id"], ["id"]
        )
        batch_op.create_index(op.f("ix_krs_detail_kelas_id"), ["kelas_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema: kembalikan kolom matakuliah & tabel ruangan/jadwal_kuliah versi sebelumnya."""
    bind = op.get_bind()
    existing_rooms = bind.execute(
        sa.text("SELECT kode, nama, kapasitas, gedung FROM ruangan")
    ).fetchall()

    with op.batch_alter_table("krs_detail") as batch_op:
        batch_op.drop_index(op.f("ix_krs_detail_kelas_id"))
        batch_op.drop_constraint("fk_krs_detail_kelas_id", type_="foreignkey")
        batch_op.drop_column("kelas_id")

    with op.batch_alter_table("matakuliah", recreate="always") as batch_op:
        batch_op.add_column(
            sa.Column("hari", sa.Integer(), server_default="1", nullable=False)
        )
        batch_op.add_column(
            sa.Column("jam_mulai", sa.Time(), server_default="08:00:00", nullable=False)
        )
        batch_op.add_column(
            sa.Column("jam_selesai", sa.Time(), server_default="10:00:00", nullable=False)
        )
        batch_op.create_check_constraint("ck_matakuliah_jam", "jam_mulai < jam_selesai")

    op.drop_index("ix_jadwal_hari_dosen", table_name="jadwal")
    op.drop_index("ix_jadwal_hari_ruangan", table_name="jadwal")
    op.drop_index(op.f("ix_jadwal_kelas_id"), table_name="jadwal")
    op.drop_table("jadwal")

    op.drop_index(op.f("ix_kelas_kode_mk"), table_name="kelas")
    op.drop_table("kelas")

    op.drop_index(op.f("ix_dosen_nidn"), table_name="dosen")
    op.drop_table("dosen")

    op.drop_table("ruangan")

    op.create_table(
        "ruangan",
        sa.Column("kode_ruangan", sa.String(length=20), nullable=False),
        sa.Column("nama", sa.String(length=100), nullable=False),
        sa.Column("kapasitas", sa.Integer(), nullable=False),
        sa.Column("gedung", sa.String(length=50), nullable=True),
        sa.CheckConstraint("kapasitas > 0", name="ck_ruangan_kapasitas"),
        sa.PrimaryKeyConstraint("kode_ruangan"),
    )
    for kode_r, nama_r, kap_r, gedung_r in existing_rooms:
        bind.execute(
            sa.text(
                "INSERT INTO ruangan (kode_ruangan, nama, kapasitas, gedung) "
                "VALUES (:kode_ruangan, :nama, :kapasitas, :gedung)"
            ),
            {"kode_ruangan": kode_r, "nama": nama_r, "kapasitas": kap_r, "gedung": gedung_r},
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
