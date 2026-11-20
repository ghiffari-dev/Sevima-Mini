from __future__ import annotations

from datetime import date, datetime, time, timezone
import enum
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


# ---------------------------------------------------------------------------
# Exception polimorfik modul presensi (ditangani @app.exception_handler)
# ---------------------------------------------------------------------------


class AttendanceError(ValueError):
    """Exception dasar modul presensi dengan status HTTP & header polimorfik."""

    status_code: int = 400

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        if status_code is not None:
            self.status_code = status_code
        self.headers: dict[str, str] = dict(headers or {})

    def body(self) -> dict[str, Any]:
        return {"success": False, "detail": str(self)}


class AttendanceNotFoundError(AttendanceError):
    """Jadwal, kelas, atau sesi presensi tidak ditemukan (404)."""

    status_code: int = 404


class AttendanceForbiddenError(AttendanceError):
    """Aktor tidak berhak (bukan dosen pengampu / bukan pemilik data) (403)."""

    status_code: int = 403


class QRTokenInvalidError(AttendanceError):
    """Token QR rusak, dipalsukan, salah tipe, atau bukan milik sesi mana pun (400)."""

    status_code: int = 400


class QRExpiredError(AttendanceError):
    """Token QR sudah berganti (rotasi) / sesi ditutup sehingga tidak berlaku lagi (410)."""

    status_code: int = 410


class OutsideAttendanceWindowError(AttendanceError):
    """Scan/buka sesi di luar jadwal kuliah atau di luar window waktu valid (422)."""

    status_code: int = 422


class NotEnrolledError(AttendanceError):
    """Mahasiswa tidak terdaftar (KRS APPROVED) di kelas sesi presensi ini (403)."""

    status_code: int = 403


class DuplicateAttendanceError(AttendanceError):
    """Mahasiswa sudah tercatat presensi pada sesi ini (409)."""

    status_code: int = 409


class GeolocationRequiredError(AttendanceError):
    """Koordinat GPS wajib dikirim karena validasi lokasi aktif (422)."""

    status_code: int = 422


class GeolocationError(AttendanceError):
    """Posisi mahasiswa di luar radius ruang kuliah / akurasi GPS terlalu buruk (403)."""

    status_code: int = 403


class SessionAlreadyOpenError(AttendanceError):
    """Sesi presensi untuk jadwal & tanggal yang sama sudah pernah dibuat (409)."""

    status_code: int = 409


class RateLimitExceededError(AttendanceError):
    """Terlalu banyak percobaan scan dalam jendela waktu tertentu (429)."""

    status_code: int = 429


# ---------------------------------------------------------------------------
# Enum status
# ---------------------------------------------------------------------------


class AttendanceStatus(str, enum.Enum):
    """Status presensi; `alpha` tidak disimpan, melainkan diturunkan dari ketiadaan record."""

    HADIR = "hadir"
    TERLAMBAT = "terlambat"
    ALPHA = "alpha"


class SessionStatus(str, enum.Enum):
    """Status sesi presensi per pertemuan."""

    OPEN = "open"
    CLOSED = "closed"


def as_utc(value: datetime | None) -> datetime | None:
    """Menormalkan datetime dari SQLite (naive) menjadi aware UTC."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Tabel
# ---------------------------------------------------------------------------


class AttendanceSession(Base):
    """Satu pertemuan kuliah yang presensinya dibuka dosen (sumber token QR berotasi)."""

    __tablename__ = "attendance_session"
    __table_args__ = (
        CheckConstraint(
            "status IN ('open', 'closed')", name="ck_attendance_session_status"
        ),
        CheckConstraint("hari BETWEEN 1 AND 6", name="ck_attendance_session_hari"),
        CheckConstraint("pertemuan_ke >= 1", name="ck_attendance_session_pertemuan"),
        UniqueConstraint(
            "kelas_id", "tanggal", "jam_mulai", name="uq_attendance_session_kelas_slot"
        ),
        UniqueConstraint(
            "kelas_id", "pertemuan_ke", name="uq_attendance_session_kelas_pertemuan"
        ),
        Index("ix_attendance_session_kelas_tanggal", "kelas_id", "tanggal"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # SET NULL: riwayat presensi tetap utuh walau jadwal kemudian dihapus admin.
    jadwal_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("jadwal.id", ondelete="SET NULL"), nullable=True, index=True
    )
    kelas_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("kelas.id"), nullable=False, index=True
    )
    dosen_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("dosen.id"), nullable=False
    )
    tanggal: Mapped[date] = mapped_column(Date, nullable=False)
    pertemuan_ke: Mapped[int] = mapped_column(Integer, nullable=False)
    # Snapshot jadwal saat sesi dibuka (jadwal bisa berubah setelahnya).
    hari: Mapped[int] = mapped_column(Integer, nullable=False)
    jam_mulai: Mapped[time] = mapped_column(Time, nullable=False)
    jam_selesai: Mapped[time] = mapped_column(Time, nullable=False)
    ruangan_kode: Mapped[str | None] = mapped_column(String(20), nullable=True)

    status: Mapped[str] = mapped_column(
        String(10), default=SessionStatus.OPEN.value, nullable=False
    )
    # Rahasia per sesi untuk nonce QR: token sesi lain / sesi yang dibuka ulang tak berlaku.
    secret: Mapped[str] = mapped_column(String(64), nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closes_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Geofence (opsional): titik pusat dari perangkat dosen di ruang kelas.
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    radius_m: Mapped[int | None] = mapped_column(Integer, nullable=True)

    records: Mapped[list["AttendanceRecord"]] = relationship(
        "AttendanceRecord",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="AttendanceRecord.scanned_at",
    )

    @property
    def opened_at_utc(self) -> datetime:
        return as_utc(self.opened_at)  # type: ignore[return-value]

    @property
    def closes_at_utc(self) -> datetime:
        return as_utc(self.closes_at)  # type: ignore[return-value]

    @property
    def is_open(self) -> bool:
        return self.status == SessionStatus.OPEN.value

    @property
    def geofence_enabled(self) -> bool:
        return self.latitude is not None and self.longitude is not None


class AttendanceRecord(Base):
    """Bukti kehadiran satu mahasiswa pada satu sesi (unik per sesi + NIM)."""

    __tablename__ = "attendance_record"
    __table_args__ = (
        CheckConstraint(
            "status IN ('hadir', 'terlambat')", name="ck_attendance_record_status"
        ),
        UniqueConstraint("session_id", "nim", name="uq_attendance_record_session_nim"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("attendance_session.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    nim: Mapped[str] = mapped_column(
        String(20), ForeignKey("calon_mahasiswa.nim"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(10), nullable=False)
    scanned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    qr_window: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    accuracy_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    distance_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)

    session: Mapped["AttendanceSession"] = relationship(
        "AttendanceSession", back_populates="records"
    )

    @property
    def scanned_at_utc(self) -> datetime:
        return as_utc(self.scanned_at)  # type: ignore[return-value]
