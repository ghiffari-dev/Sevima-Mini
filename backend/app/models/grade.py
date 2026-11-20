from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    text,
)
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.enrollment import Enrollment
    from app.models.krs import KRSDetail
    from app.models.schedule import Dosen as DosenJadwal


class GradeError(ValueError):
    """Exception dasar untuk pelanggaran aturan input & audit nilai (polimorfik HTTP)."""

    status_code: int = 400

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        if status_code is not None:
            self.status_code = status_code

    def body(self) -> dict[str, Any]:
        """Membentuk payload JSON error secara polimorfik untuk FastAPI handler."""
        return {"detail": str(self)}


class GradeForbiddenError(GradeError):
    """Exception ketika pengguna bukan dosen pengampu kelas yang bersangkutan (403 Forbidden)."""

    status_code: int = 403


class GradeNotFoundError(GradeError):
    """Exception ketika kelas, mahasiswa, atau baris KRSDetail tidak ditemukan (404 Not Found)."""

    status_code: int = 404


class PresensiKurangError(GradeError):
    """Exception ketika presensi mahasiswa di bawah batas minimal 75% (422 Unprocessable Entity)."""

    status_code: int = 422


class AlasanWajibError(GradeError):
    """Exception ketika perubahan nilai yang sudah ada tidak disertai alasan (422)."""

    status_code: int = 422


class HurufTidakValidError(GradeError):
    """Exception ketika huruf nilai tidak terdaftar pada tabel skala_nilai (422)."""

    status_code: int = 422


DEFAULT_SKALA_NILAI: tuple[tuple[str, Decimal, bool], ...] = (
    ("A", Decimal("4.00"), True),
    ("B", Decimal("3.00"), True),
    ("C", Decimal("2.00"), True),
    ("D", Decimal("1.00"), False),  # Asumsi sementara: minimal C lulus sambil menunggu stakeholder
    ("E", Decimal("0.00"), False),
)


class SkalaNilai(Base):
    """Tabel referensi huruf nilai, bobot Decimal NUMERIC(3,2), dan status kelulusan berbasis data."""

    __tablename__ = "skala_nilai"
    __table_args__ = (
        CheckConstraint("bobot >= 0 AND bobot <= 4", name="ck_skala_nilai_bobot"),
    )

    huruf: Mapped[str] = mapped_column(String(2), primary_key=True)
    bobot: Mapped[Decimal] = mapped_column(
        Numeric(3, 2, asdecimal=True), nullable=False
    )
    lulus: Mapped[bool] = mapped_column(Boolean, nullable=False)


def seed_skala_nilai(db: Session) -> None:
    """Mengisi baris default skala_nilai (A..E) secara idempoten apabila belum tersedia."""
    for huruf, bobot, lulus in DEFAULT_SKALA_NILAI:
        if db.get(SkalaNilai, huruf) is None:
            db.add(SkalaNilai(huruf=huruf, bobot=bobot, lulus=lulus))
    db.flush()


class GradeHistory(Base):
    """Tabel audit trail append-only untuk setiap input pertama maupun perubahan nilai KRSDetail."""

    __tablename__ = "grade_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Nama kolom `grade_id` dipertahankan sesuai dokumen tugas dan merujuk ke `krs_detail.id`
    grade_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("krs_detail.id"), nullable=False, index=True
    )
    nilai_lama: Mapped[str | None] = mapped_column(
        String(2), ForeignKey("skala_nilai.huruf"), nullable=True
    )
    nilai_baru: Mapped[str] = mapped_column(
        String(2), ForeignKey("skala_nilai.huruf"), nullable=False
    )
    diubah_oleh: Mapped[int] = mapped_column(
        Integer, ForeignKey("dosen.id"), nullable=False, index=True
    )
    diubah_pada: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    alasan: Mapped[str | None] = mapped_column(String(500), nullable=True)

    krs_detail: Mapped["KRSDetail"] = relationship(
        "app.models.krs.KRSDetail", back_populates="histories"
    )
    dosen: Mapped["DosenJadwal"] = relationship("app.models.schedule.Dosen")


RIWAYAT_NILAI_VIEW_SQL: str = """
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


def ensure_riwayat_nilai_view(target: Session | Connection | Engine) -> None:
    """Memastikan SQL View `riwayat_nilai` tersedia di database (termasuk SQLite in-memory tes)."""
    if isinstance(target, Engine):
        with target.begin() as conn:
            conn.execute(text(RIWAYAT_NILAI_VIEW_SQL))
    else:
        target.execute(text(RIWAYAT_NILAI_VIEW_SQL))


class Grade(Base):
    """Model legacy Minggu 1-4 (dipertahankan untuk backward-compatibility test lama).

    Catatan arsitektur (Minggu 9): Single source of truth nilai akademik menggunakan
    `krs_detail.nilai` (FK ke `skala_nilai.huruf`) dan audit trail `grade_history`.
    """

    __tablename__ = "grades"

    enrollment_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("enrollments.id_enrollment"), primary_key=True
    )
    nilaiAngka: Mapped[float] = mapped_column(Float, nullable=False)
    nilaiHuruf: Mapped[str] = mapped_column(String(5), nullable=False)
    bobot: Mapped[float] = mapped_column(Float, nullable=False)

    enrollment: Mapped["Enrollment"] = relationship("Enrollment", back_populates="grade")
