import enum
from datetime import time
from sqlalchemy import (
    CheckConstraint,
    Column,
    Enum,
    ForeignKey,
    Integer,
    String,
    Table,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base


prerequisite = Table(
    "prerequisite",
    Base.metadata,
    Column("kode_mk", String(10), ForeignKey("matakuliah.kode_mk"), primary_key=True),
    Column("kode_prasyarat", String(10), ForeignKey("matakuliah.kode_mk"), primary_key=True),
    CheckConstraint("kode_mk <> kode_prasyarat", name="ck_prerequisite_not_self"),
)


class MataKuliah(Base):
    __tablename__ = "matakuliah"
    __table_args__ = (
        CheckConstraint("sks BETWEEN 1 AND 4", name="ck_matakuliah_sks"),
        CheckConstraint("jam_mulai < jam_selesai", name="ck_matakuliah_jam"),
    )

    kode_mk: Mapped[str] = mapped_column(String(10), primary_key=True)
    nama: Mapped[str] = mapped_column(String(100), nullable=False)
    sks: Mapped[int] = mapped_column(Integer, nullable=False)
    hari: Mapped[int] = mapped_column(Integer, nullable=False)  # 1 = Senin ... 6 = Sabtu
    jam_mulai: Mapped[time] = mapped_column(Time, nullable=False)
    jam_selesai: Mapped[time] = mapped_column(Time, nullable=False)

    prasyarat: Mapped[list["MataKuliah"]] = relationship(
        "MataKuliah",
        secondary=prerequisite,
        primaryjoin=kode_mk == prerequisite.c.kode_mk,
        secondaryjoin=kode_mk == prerequisite.c.kode_prasyarat,
    )


class KRSStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REVISION = "REVISION"


class KRS(Base):
    __tablename__ = "krs"
    __table_args__ = (UniqueConstraint("nim", "semester", name="uq_krs_nim_semester"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    nim: Mapped[str] = mapped_column(
        String(20), ForeignKey("calon_mahasiswa.nim"), nullable=False, index=True
    )
    semester: Mapped[str] = mapped_column(String(5), nullable=False)  # Contoh: "20251"
    status: Mapped[KRSStatus] = mapped_column(
        Enum(KRSStatus), default=KRSStatus.DRAFT, nullable=False
    )
    dosen_pa_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    details: Mapped[list["KRSDetail"]] = relationship(
        "KRSDetail", back_populates="krs", cascade="all, delete-orphan"
    )


class KRSDetail(Base):
    __tablename__ = "krs_detail"
    __table_args__ = (UniqueConstraint("krs_id", "kode_mk", name="uq_krs_detail_mk"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    krs_id: Mapped[int] = mapped_column(ForeignKey("krs.id"), nullable=False)
    kode_mk: Mapped[str] = mapped_column(
        String(10), ForeignKey("matakuliah.kode_mk"), nullable=False
    )
    nilai: Mapped[str | None] = mapped_column(String(2), nullable=True)

    krs: Mapped["KRS"] = relationship("KRS", back_populates="details")
    matakuliah: Mapped["MataKuliah"] = relationship("MataKuliah")
