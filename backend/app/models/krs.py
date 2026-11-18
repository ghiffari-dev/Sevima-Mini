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
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates
from app.models.base import Base


class KRSError(ValueError):
    """Exception dasar untuk pelanggaran aturan bisnis dan state machine KRS."""
    pass


class StateTransitionError(KRSError):
    """Exception khusus ketika transisi status KRS tidak sah."""
    pass


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


# Tabel transisi berbasis dict[(state, aktor)] -> himpunan state tujuan yang diizinkan
TRANSITIONS: dict[tuple[KRSStatus, str], set[KRSStatus]] = {
    (KRSStatus.DRAFT, "mahasiswa"): {KRSStatus.SUBMITTED},
    (KRSStatus.SUBMITTED, "dosen"): {KRSStatus.APPROVED, KRSStatus.REVISION},
    (KRSStatus.REVISION, "mahasiswa"): {KRSStatus.SUBMITTED},
}


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

    def __init__(self, **kwargs):
        kwargs.setdefault("status", KRSStatus.DRAFT)
        self._allow_status_change = True
        try:
            super().__init__(**kwargs)
        finally:
            self._allow_status_change = False

    @validates("status")
    def _validate_status_assignment(self, key: str, value: KRSStatus) -> KRSStatus:
        if not getattr(self, "_allow_status_change", False):
            raise StateTransitionError(
                "Status KRS hanya boleh diubah lewat transition()"
            )
        return value if isinstance(value, KRSStatus) else KRSStatus(value)

    def transition(
        self,
        new_status: KRSStatus,
        actor: str = "mahasiswa",
        dosen_id: int | None = None,
    ) -> KRSStatus:
        """Mengubah status KRS sesuai tabel transisi dict[(state, aktor)] dan aturan bisnis."""
        if not isinstance(new_status, KRSStatus):
            new_status = KRSStatus(new_status)

        actor_norm = actor.strip().lower()
        allowed_targets = TRANSITIONS.get((self.status, actor_norm), set())
        if new_status not in allowed_targets:
            raise StateTransitionError(
                f"Transisi tidak diizinkan: {self.status.value} ke {new_status.value}"
            )

        if new_status == KRSStatus.SUBMITTED:
            if not self.details:
                raise StateTransitionError("KRS kosong tidak dapat di-submit")

        if actor_norm == "dosen":
            if self.dosen_pa_id is None or dosen_id != self.dosen_pa_id:
                raise StateTransitionError(
                    "Approve/revise hanya boleh dilakukan oleh Dosen PA mahasiswa ini"
                )

        self._allow_status_change = True
        try:
            self.status = new_status
        finally:
            self._allow_status_change = False
        return self.status


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
