from __future__ import annotations

from datetime import datetime, time, timezone
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Time,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.krs import MataKuliah


class ScheduleError(ValueError):
    """Exception dasar untuk pelanggaran aturan penjadwalan & kapasitas ruangan."""

    def __init__(
        self,
        message: str,
        status_code: int = 400,
        conflicts: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.conflicts = conflicts


class ScheduleConflictError(ScheduleError):
    """Exception ketika jadwal memiliki bentrok ruangan, dosen, atau waktu (409 Conflict)."""

    def __init__(
        self,
        message: str,
        conflicts: list[dict[str, Any]] | None = None,
        status_code: int = 409,
    ) -> None:
        super().__init__(message, status_code=status_code, conflicts=conflicts)


class ScheduleCapacityError(ScheduleError):
    """Exception ketika jumlah mahasiswa melebihi kapasitas ruangan (400 Bad Request)."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message, status_code=status_code)


class ScheduleNotFoundError(ScheduleError):
    """Exception ketika ruangan atau jadwal kuliah tidak ditemukan (404 Not Found)."""

    def __init__(self, message: str, status_code: int = 404) -> None:
        super().__init__(message, status_code=status_code)


HARI_MAP: dict[int, str] = {
    1: "Senin",
    2: "Selasa",
    3: "Rabu",
    4: "Kamis",
    5: "Jumat",
    6: "Sabtu",
}

_HARI_REVERSE: dict[str, int] = {
    **{v.lower(): k for k, v in HARI_MAP.items()},
    "sen": 1,
    "sel": 2,
    "rab": 3,
    "kam": 4,
    "jum": 5,
    "sab": 6,
    "monday": 1,
    "tuesday": 2,
    "wednesday": 3,
    "thursday": 4,
    "friday": 5,
    "saturday": 6,
}


def normalize_hari(value: int | str) -> int:
    """Mengonversi angka 1-6 atau nama hari Indonesia/Inggris menjadi kode integer 1-6."""
    if isinstance(value, bool):
        raise ScheduleError(f"Hari tidak valid: {value}")
    if isinstance(value, int):
        if 1 <= value <= 6:
            return value
        raise ScheduleError(f"Hari harus di antara 1 (Senin) dan 6 (Sabtu), dapat: {value}")

    text = str(value).strip()
    if text.isdigit():
        num = int(text)
        if 1 <= num <= 6:
            return num
    mapped = _HARI_REVERSE.get(text.lower())
    if mapped is not None:
        return mapped
    raise ScheduleError(f"Hari tidak dikenal: {value}")


def format_hari(value: int | str) -> str:
    """Mengembalikan nama hari berbahasa Indonesia dari angka 1-6 atau string hari."""
    return HARI_MAP[normalize_hari(value)]


class Ruangan(Base):
    """Model master ruangan kuliah beserta kapasitas kursi."""

    __tablename__ = "ruangan"
    __table_args__ = (
        CheckConstraint("kapasitas > 0", name="ck_ruangan_kapasitas"),
    )

    kode_ruangan: Mapped[str] = mapped_column(String(20), primary_key=True)
    nama: Mapped[str] = mapped_column(String(100), nullable=False)
    kapasitas: Mapped[int] = mapped_column(Integer, nullable=False)
    gedung: Mapped[str | None] = mapped_column(String(50), nullable=True)

    schedules: Mapped[list["JadwalKuliah"]] = relationship(
        "JadwalKuliah", back_populates="ruangan"
    )


class JadwalKuliah(Base):
    """Model jadwal perkuliahan per mata kuliah, ruangan, dosen, dan semester."""

    __tablename__ = "jadwal_kuliah"
    __table_args__ = (
        CheckConstraint("hari BETWEEN 1 AND 6", name="ck_jadwal_hari"),
        CheckConstraint("jam_mulai < jam_selesai", name="ck_jadwal_jam"),
        CheckConstraint("enrolled_count >= 0", name="ck_jadwal_enrolled"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kode_mk: Mapped[str] = mapped_column(
        String(10), ForeignKey("matakuliah.kode_mk"), nullable=False, index=True
    )
    ruangan_kode: Mapped[str] = mapped_column(
        String(20), ForeignKey("ruangan.kode_ruangan"), nullable=False, index=True
    )
    dosen: Mapped[str] = mapped_column(String(120), nullable=False)
    semester: Mapped[str] = mapped_column(String(10), default="20251", nullable=False)
    hari: Mapped[int] = mapped_column(Integer, nullable=False)
    jam_mulai: Mapped[time] = mapped_column(Time, nullable=False)
    jam_selesai: Mapped[time] = mapped_column(Time, nullable=False)
    enrolled_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    matakuliah: Mapped["MataKuliah"] = relationship("MataKuliah")
    ruangan: Mapped["Ruangan"] = relationship("Ruangan", back_populates="schedules")
