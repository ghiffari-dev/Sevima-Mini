"""tambah tabel skala_nilai, fk krs_detail.nilai, tabel grade_history, dan view riwayat_nilai (minggu 9)

Revision ID: d4e5f6grd010
Revises: c3d4e5sch009
Create Date: 2026-11-20 15:40:00.000000

"""
from decimal import Decimal
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d4e5f6grd010"
down_revision: Union[str, Sequence[str], None] = "c3d4e5sch009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_RIWAYAT_NILAI_VIEW_SQL = """
CREATE VIEW IF NOT EXISTS riwayat_nilai AS
SELECT
    gh.id,
    gh.grade_id,
    k.nim,
    k.semester,
    kd.kode_mk,
    mk.nama AS nama_mk,
    kd.kelas_id,
    gh.nilai_lama,
    gh.nilai_baru,
    gh.diubah_oleh,
    d.nama AS nama_dosen,
    gh.diubah_pada,
    gh.alasan
FROM grade_history gh
JOIN krs_detail kd ON gh.grade_id = kd.id
JOIN krs k ON kd.krs_id = k.id
JOIN matakuliah mk ON kd.kode_mk = mk.kode_mk
JOIN dosen d ON gh.diubah_oleh = d.id
""".strip()


def upgrade() -> None:
    """Membuat skala_nilai (A..E + lulus), FK krs_detail.nilai, grade_history, dan view riwayat_nilai."""
    op.create_table(
        "skala_nilai",
        sa.Column("huruf", sa.String(length=2), nullable=False),
        sa.Column("bobot", sa.Numeric(precision=3, scale=2), nullable=False),
        sa.Column("lulus", sa.Boolean(), nullable=False),
        sa.CheckConstraint("bobot >= 0 AND bobot <= 4", name="ck_skala_nilai_bobot"),
        sa.PrimaryKeyConstraint("huruf"),
    )

    skala_tbl = sa.table(
        "skala_nilai",
        sa.column("huruf", sa.String(length=2)),
        sa.column("bobot", sa.Numeric(precision=3, scale=2, asdecimal=True)),
        sa.column("lulus", sa.Boolean()),
    )
    op.bulk_insert(
        skala_tbl,
        [
            {"huruf": "A", "bobot": Decimal("4.00"), "lulus": True},
            {"huruf": "B", "bobot": Decimal("3.00"), "lulus": True},
            {"huruf": "C", "bobot": Decimal("2.00"), "lulus": True},
            {"huruf": "D", "bobot": Decimal("1.00"), "lulus": False},
            {"huruf": "E", "bobot": Decimal("0.00"), "lulus": False},
        ],
    )

    with op.batch_alter_table("krs_detail") as batch_op:
        batch_op.create_foreign_key(
            "fk_krs_detail_nilai_skala_nilai",
            "skala_nilai",
            ["nilai"],
            ["huruf"],
        )

    op.create_table(
        "grade_history",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("grade_id", sa.Integer(), nullable=False),
        sa.Column("nilai_lama", sa.String(length=2), nullable=True),
        sa.Column("nilai_baru", sa.String(length=2), nullable=False),
        sa.Column("diubah_oleh", sa.Integer(), nullable=False),
        sa.Column("diubah_pada", sa.DateTime(timezone=True), nullable=False),
        sa.Column("alasan", sa.String(length=500), nullable=True),
        sa.ForeignKeyConstraint(["diubah_oleh"], ["dosen.id"]),
        sa.ForeignKeyConstraint(["grade_id"], ["krs_detail.id"]),
        sa.ForeignKeyConstraint(["nilai_baru"], ["skala_nilai.huruf"]),
        sa.ForeignKeyConstraint(["nilai_lama"], ["skala_nilai.huruf"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_grade_history_grade_id"), "grade_history", ["grade_id"], unique=False
    )
    op.create_index(
        op.f("ix_grade_history_diubah_oleh"),
        "grade_history",
        ["diubah_oleh"],
        unique=False,
    )

    op.execute(sa.text(_RIWAYAT_NILAI_VIEW_SQL))


def downgrade() -> None:
    """Menghapus view riwayat_nilai, grade_history, FK krs_detail.nilai, dan skala_nilai."""
    op.execute(sa.text("DROP VIEW IF EXISTS riwayat_nilai"))

    op.drop_index(op.f("ix_grade_history_diubah_oleh"), table_name="grade_history")
    op.drop_index(op.f("ix_grade_history_grade_id"), table_name="grade_history")
    op.drop_table("grade_history")

    with op.batch_alter_table("krs_detail") as batch_op:
        batch_op.drop_constraint(
            "fk_krs_detail_nilai_skala_nilai", type_="foreignkey"
        )

    op.drop_table("skala_nilai")
