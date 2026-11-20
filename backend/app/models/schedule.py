from __future__ import annotations

from datetime import datetime, time, timezone
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.krs import MataKuliah


class ScheduleError(ValueError):
    """Exception dasar untuk pelanggaran aturan penjadwalan & kapasitas ruangan."""

    status_code: int = 400

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        conflicts: list[Any] | None = None,
    ) -> None:
        super().__init__(message)
        if status_code is not None:
            self.status_code = status_code
        self.conflicts = conflicts or []

    def body(self) -> dict[str, Any]:
        """Membentuk payload JSON error secara polimorfik."""
        return {"detail": str(self)}


class ScheduleNotFoundError(ScheduleError):
    """Exception ketika ruangan, dosen, kelas, atau jadwal tidak ditemukan (404 Not Found)."""

    status_code: int = 404


class ScheduleCapacityError(ScheduleError):
    """Exception ketika kebutuhan kursi kelas melebihi kapasitas ruangan (409 Conflict)."""

    status_code: int = 409


class ScheduleConflictError(ScheduleError):
    """Exception ketika jadwal memiliki bentrok ruangan atau dosen (409 Conflict)."""

    status_code: int = 409

    def __init__(
        self,
        message: str,
        conflicts: list[Any] | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(
            message,
            status_code=status_code if status_code is not None else 409,
            conflicts=conflicts,
        )

    def body(self) -> dict[str, Any]:
        serialized: list[dict[str, Any]] = []
        for item in self.conflicts:
            if hasattr(item, "to_dict"):
                serialized.append(item.to_dict())
            elif isinstance(item, dict):
                serialized.append(item)
            else:
                serialized.append({"detail": str(item)})
        return {"detail": str(self), "conflicts": serialized}


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
    """Model master ruangan kuliah dengan kode sebagai identitas alami dan kapasitas."""

    __tablename__ = "ruangan"
    __table_args__ = (
        CheckConstraint("kapasitas > 0", name="ck_ruangan_kapasitas"),
    )

    kode: Mapped[str] = mapped_column(String(20), primary_key=True)
    nama: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    kapasitas: Mapped[int] = mapped_column(Integer, nullable=False)
    gedung: Mapped[str | None] = mapped_column(String(50), nullable=True)

    jadwals: Mapped[list["Jadwal"]] = relationship(
        "app.models.schedule.Jadwal", back_populates="ruangan"
    )

    def __init__(self, **kwargs: Any) -> None:
        if "kode" not in kwargs and "kode_ruangan" in kwargs:
            kwargs["kode"] = kwargs.pop("kode_ruangan")
        else:
            kwargs.pop("kode_ruangan", None)
        if not kwargs.get("nama") and kwargs.get("kode"):
            kwargs["nama"] = kwargs["kode"]
        super().__init__(**kwargs)

    @property
    def kode_ruangan(self) -> str:
        return self.kode

    @property
    def schedules(self) -> list["Jadwal"]:
        return self.jadwals


class Dosen(Base):
    """Model master dosen pengampu dengan NIDN unik."""

    __tablename__ = "dosen"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nidn: Mapped[str] = mapped_column(String(20), unique=True, index=True, nullable=False)
    nama: Mapped[str] = mapped_column(String(120), nullable=False)

    jadwals: Mapped[list["Jadwal"]] = relationship(
        "app.models.schedule.Jadwal", back_populates="dosen"
    )


class Kelas(Base):
    """Model kelas paralel dari sebuah MataKuliah dengan kuota dan semester."""

    __tablename__ = "kelas"
    __table_args__ = (
        CheckConstraint("kuota > 0", name="ck_kelas_kuota"),
        UniqueConstraint("kode_mk", "nama_kelas", "semester", name="uq_kelas_mk_nama_semester"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kode_mk: Mapped[str] = mapped_column(
        String(10), ForeignKey("matakuliah.kode_mk"), nullable=False, index=True
    )
    nama_kelas: Mapped[str] = mapped_column(String(20), nullable=False)
    kuota: Mapped[int] = mapped_column(Integer, default=40, nullable=False)
    semester: Mapped[str] = mapped_column(String(10), default="20251", nullable=False)

    matakuliah: Mapped["MataKuliah"] = relationship(
        "app.models.krs.MataKuliah", back_populates="kelas"
    )
    jadwals: Mapped[list["Jadwal"]] = relationship(
        "app.models.schedule.Jadwal",
        back_populates="kelas",
        cascade="all, delete-orphan",
    )


class Jadwal(Base):
    """Model satu pertemuan mingguan yang mengikat Kelas, Ruangan, dan Dosen."""

    __tablename__ = "jadwal"
    __table_args__ = (
        CheckConstraint("hari BETWEEN 1 AND 6", name="ck_jadwal_hari"),
        CheckConstraint("jam_mulai < jam_selesai", name="ck_jadwal_jam"),
        Index("ix_jadwal_hari_ruangan", "hari", "ruangan_kode"),
        Index("ix_jadwal_hari_dosen", "hari", "dosen_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kelas_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("kelas.id"), nullable=False, index=True
    )
    ruangan_kode: Mapped[str] = mapped_column(
        String(20), ForeignKey("ruangan.kode"), nullable=False
    )
    dosen_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("dosen.id"), nullable=False
    )
    hari: Mapped[int] = mapped_column(Integer, nullable=False)
    jam_mulai: Mapped[time] = mapped_column(Time, nullable=False)
    jam_selesai: Mapped[time] = mapped_column(Time, nullable=False)
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

    kelas: Mapped["Kelas"] = relationship(
        "app.models.schedule.Kelas", back_populates="jadwals"
    )
    ruangan: Mapped["Ruangan"] = relationship(
        "app.models.schedule.Ruangan", back_populates="jadwals"
    )
    dosen: Mapped["Dosen"] = relationship(
        "app.models.schedule.Dosen", back_populates="jadwals"
    )


JadwalKuliah = Jadwal
