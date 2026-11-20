import enum
from datetime import datetime, time, timezone
from typing import TYPE_CHECKING, Any
from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Table,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, reconstructor, relationship, validates
from app.models.base import Base

if TYPE_CHECKING:
    from app.models.grade import GradeHistory, SkalaNilai
    from app.models.schedule import Kelas


class KRSError(ValueError):
    """Exception dasar untuk pelanggaran aturan bisnis dan state machine KRS."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


class TransitionError(KRSError):
    """Exception khusus ketika transisi status KRS tidak sah (409 Conflict)."""

    def __init__(self, message: str, status_code: int = 409) -> None:
        super().__init__(message, status_code=status_code)


class KRSLockedError(TransitionError):
    """Exception khusus ketika KRS sedang terkunci/tidak berstatus EDITABLE (409 Conflict)."""

    status_code = 409

    def __init__(self, message: str, status_code: int = 409) -> None:
        super().__init__(message, status_code=status_code)


StateTransitionError = TransitionError


class KRSForbiddenError(KRSError):
    """Exception khusus ketika aktor tidak berhak mengakses/mengubah KRS (403 Forbidden)."""

    def __init__(self, message: str, status_code: int = 403) -> None:
        super().__init__(message, status_code=status_code)


ForbiddenError = KRSForbiddenError


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
    )

    kode_mk: Mapped[str] = mapped_column(String(10), primary_key=True)
    nama: Mapped[str] = mapped_column(String(100), nullable=False)
    sks: Mapped[int] = mapped_column(Integer, nullable=False)

    prasyarat: Mapped[list["MataKuliah"]] = relationship(
        "MataKuliah",
        secondary=prerequisite,
        primaryjoin=kode_mk == prerequisite.c.kode_mk,
        secondaryjoin=kode_mk == prerequisite.c.kode_prasyarat,
    )
    kelas: Mapped[list["Kelas"]] = relationship(
        "app.models.schedule.Kelas", back_populates="matakuliah"
    )

    def __init__(self, **kwargs: Any) -> None:
        hari = kwargs.pop("hari", None)
        jam_mulai = kwargs.pop("jam_mulai", None)
        jam_selesai = kwargs.pop("jam_selesai", None)
        super().__init__(**kwargs)
        self._transient_slots: list[tuple[int, time, time]] = []
        if hari is not None and jam_mulai is not None and jam_selesai is not None:
            self._transient_slots.append((int(hari), jam_mulai, jam_selesai))

    @reconstructor
    def _init_on_load(self) -> None:
        self._transient_slots = []

    def get_jadwal_slots(self) -> list[tuple[int, time, time]]:
        """Mengambil daftar slot (hari, jam_mulai, jam_selesai) dari kelas->jadwals atau fallback transient."""
        slots: list[tuple[int, time, time]] = []
        for kls in (self.kelas or []):
            for j in (kls.jadwals or []):
                slots.append((j.hari, j.jam_mulai, j.jam_selesai))
        if slots:
            return slots
        return list(getattr(self, "_transient_slots", []))

    @property
    def hari(self) -> int | None:
        slots = self.get_jadwal_slots()
        return slots[0][0] if slots else None

    @property
    def jam_mulai(self) -> time | None:
        slots = self.get_jadwal_slots()
        return slots[0][1] if slots else None

    @property
    def jam_selesai(self) -> time | None:
        slots = self.get_jadwal_slots()
        return slots[0][2] if slots else None


class KRSStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REVISION = "REVISION"


class Actor(str, enum.Enum):
    MAHASISWA = "mahasiswa"
    DOSEN_PA = "dosen_pa"
    SYSTEM = "system"


def _normalize_actor(actor: Actor | str) -> Actor:
    """Menormalisasi string atau Enum Actor menjadi Actor."""
    if isinstance(actor, Actor):
        return actor
    normalized = actor.strip().lower()
    if normalized == "mahasiswa":
        return Actor.MAHASISWA
    if normalized in ("dosen_pa", "dosen"):
        return Actor.DOSEN_PA
    if normalized in ("system", "sistem"):
        return Actor.SYSTEM
    raise KRSForbiddenError(f"Aktor tidak dikenal: {actor}")


# Tabel transisi berbasis dict[(state, aktor)] -> himpunan state tujuan yang diizinkan
TRANSITIONS: dict[tuple[KRSStatus, Actor], set[KRSStatus]] = {
    (KRSStatus.DRAFT, Actor.MAHASISWA): {KRSStatus.SUBMITTED},
    (KRSStatus.SUBMITTED, Actor.DOSEN_PA): {KRSStatus.APPROVED, KRSStatus.REVISION},
    (KRSStatus.REVISION, Actor.MAHASISWA): {KRSStatus.SUBMITTED},
    (KRSStatus.SUBMITTED, Actor.SYSTEM): {KRSStatus.REVISION},
    (KRSStatus.APPROVED, Actor.SYSTEM): {KRSStatus.REVISION},
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
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    catatan_revisi: Mapped[str | None] = mapped_column(String(500), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    diubah_pada: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=True,
    )

    __mapper_args__ = {"version_id_col": version}

    details: Mapped[list["KRSDetail"]] = relationship(
        "KRSDetail", back_populates="krs", cascade="all, delete-orphan"
    )
    logs: Mapped[list["KRSLog"]] = relationship(
        "KRSLog", back_populates="krs", cascade="all, delete-orphan"
    )

    def __init__(self, **kwargs):
        kwargs.setdefault("status", KRSStatus.DRAFT)
        kwargs.setdefault("version", 1)
        kwargs.setdefault("diubah_pada", datetime.now(timezone.utc))
        self._allow_status_change = True
        try:
            super().__init__(**kwargs)
        finally:
            self._allow_status_change = False

    @validates("status")
    def _validate_status_assignment(self, key: str, value: KRSStatus) -> KRSStatus:
        if not getattr(self, "_allow_status_change", False):
            raise TransitionError(
                "Status KRS hanya boleh diubah lewat transition()"
            )
        return value if isinstance(value, KRSStatus) else KRSStatus(value)

    def cek_transisi(self, target: KRSStatus, actor: Actor | str) -> None:
        """Memeriksa apakah perpindahan dari status saat ini ke target oleh actor sah."""
        if not isinstance(target, KRSStatus):
            target = KRSStatus(target)
        actor_enum = _normalize_actor(actor)

        if target not in TRANSITIONS.get((self.status, actor_enum), set()):
            raise TransitionError(
                f"Transisi tidak diizinkan: {self.status.name} ke {target.name}"
            )

    def transition(
        self,
        target: KRSStatus,
        actor: Actor | str = Actor.MAHASISWA,
        dosen_id: int | None = None,
        catatan: str | None = None,
    ) -> KRSStatus:
        """Mengubah status KRS sesuai tabel transisi dict[(state, aktor)] dan aturan bisnis."""
        if not isinstance(target, KRSStatus):
            target = KRSStatus(target)
        actor_enum = _normalize_actor(actor)

        self.cek_transisi(target, actor_enum)

        now = datetime.now(timezone.utc)
        if target == KRSStatus.SUBMITTED:
            if not self.details:
                raise KRSError("KRS kosong tidak dapat di-submit")
            self.submitted_at = now

        if actor_enum == Actor.DOSEN_PA:
            if self.dosen_pa_id is None or (
                dosen_id is not None and dosen_id != self.dosen_pa_id
            ):
                raise KRSForbiddenError(
                    "Approve/revise hanya boleh dilakukan oleh Dosen PA mahasiswa ini"
                )

        if target == KRSStatus.REVISION:
            if actor_enum == Actor.SYSTEM:
                if not catatan or not catatan.strip():
                    raise KRSError("Alasan invalidasi jadwal wajib diisi")
                self.catatan_revisi = catatan.strip()
                self.approved_at = None
            else:
                if catatan is not None and not catatan.strip():
                    raise KRSError("Catatan revisi wajib diisi oleh Dosen PA")
                if catatan is not None:
                    self.catatan_revisi = catatan.strip()
                elif not self.catatan_revisi:
                    raise KRSError("Catatan revisi wajib diisi oleh Dosen PA")

        if target == KRSStatus.APPROVED:
            self.approved_at = now

        self.diubah_pada = now
        self._allow_status_change = True
        try:
            self.status = target
        finally:
            self._allow_status_change = False
        return self.status

    def invalidate_by_schedule_change(self, reason: str) -> KRSStatus:
        """Mengembalikan status KRS ke REVISION lewat satu pintu transition() dengan Actor.SYSTEM."""
        return self.transition(
            KRSStatus.REVISION,
            actor=Actor.SYSTEM,
            catatan=reason,
        )


class KRSDetail(Base):
    __tablename__ = "krs_detail"
    __table_args__ = (UniqueConstraint("krs_id", "kode_mk", name="uq_krs_detail_mk"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    krs_id: Mapped[int] = mapped_column(ForeignKey("krs.id"), nullable=False)
    kode_mk: Mapped[str] = mapped_column(
        String(10), ForeignKey("matakuliah.kode_mk"), nullable=False
    )
    kelas_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("kelas.id"), nullable=True, index=True
    )
    nilai: Mapped[str | None] = mapped_column(
        String(2), ForeignKey("skala_nilai.huruf"), nullable=True
    )

    krs: Mapped["KRS"] = relationship("KRS", back_populates="details")
    matakuliah: Mapped["MataKuliah"] = relationship("MataKuliah")
    kelas: Mapped["Kelas | None"] = relationship("app.models.schedule.Kelas")
    skala: Mapped["SkalaNilai | None"] = relationship("app.models.grade.SkalaNilai")
    histories: Mapped[list["GradeHistory"]] = relationship(
        "app.models.grade.GradeHistory",
        back_populates="krs_detail",
        order_by="GradeHistory.id",
    )


class KRSLog(Base):
    """Catatan audit perubahan status KRS (Slide 3: satu unit kerja ACID)."""

    __tablename__ = "krs_log"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    krs_id: Mapped[int] = mapped_column(
        ForeignKey("krs.id"), nullable=False, index=True
    )
    aksi: Mapped[str] = mapped_column(String(50), nullable=False)
    oleh: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    krs: Mapped["KRS"] = relationship("KRS", back_populates="logs")


class Notifikasi(Base):
    """Baris notifikasi di DB yang disimpan dalam transaksi yang sama (Slide 3: ACID)."""

    __tablename__ = "notifikasi"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    nim: Mapped[str] = mapped_column(
        String(20), ForeignKey("calon_mahasiswa.nim"), nullable=False, index=True
    )
    pesan: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
