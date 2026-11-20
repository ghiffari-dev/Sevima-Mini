from datetime import datetime
from sqlalchemy import String, Integer, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base

class Pendaftaran(Base):
    __tablename__ = "pendaftarans"

    idPendaftaran: Mapped[str] = mapped_column(String(50), primary_key=True, index=True)
    tanggalDaftar: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="Draft", nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False)  # 'pmb', 'krs'

    __mapper_args__ = {
        "polymorphic_identity": "pendaftaran",
        "polymorphic_on": type,
    }

class PendaftaranPMB(Pendaftaran):
    __tablename__ = "pendaftaran_pmbs"

    idPendaftaran: Mapped[str] = mapped_column(String(50), ForeignKey("pendaftarans.idPendaftaran"), primary_key=True)
    pilihanJurusan: Mapped[str] = mapped_column(String(100), nullable=False)
    calon_mahasiswa_id: Mapped[int] = mapped_column(Integer, ForeignKey("calon_mahasiswa.id"), nullable=False)

    calon_mahasiswa: Mapped["CalonMahasiswa"] = relationship("CalonMahasiswa")
    payment: Mapped["PembayaranPMB | None"] = relationship("PembayaranPMB", back_populates="pendaftaran_pmb", uselist=False)

    __mapper_args__ = {
        "polymorphic_identity": "pmb",
    }

class PendaftaranKRS(Pendaftaran):
    """Representasi 1 Kartu KRS (Header) per mahasiswa per semester.
    Status persetujuan berada di level kartu, bukan per baris mata kuliah.
    """
    __tablename__ = "pendaftaran_krss"

    idPendaftaran: Mapped[str] = mapped_column(String(50), ForeignKey("pendaftarans.idPendaftaran"), primary_key=True)
    semester: Mapped[str] = mapped_column(String(20), default="2026-1", nullable=False)
    totalSks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    mahasiswa_id: Mapped[str] = mapped_column(String(50), ForeignKey("mahasiswas.id"), nullable=False)
    dosen_pa_id: Mapped[str | None] = mapped_column(String(50), ForeignKey("dosens.id"), nullable=True)

    mahasiswa: Mapped["Mahasiswa"] = relationship("Mahasiswa", back_populates="pendaftaran_krs")
    dosen_pa: Mapped["Dosen | None"] = relationship("app.models.user.Dosen", back_populates="krs_bimbingan")
    enrollments: Mapped[list["Enrollment"]] = relationship("Enrollment", back_populates="pendaftaran_krs", cascade="all, delete-orphan")
    payment: Mapped["PembayaranKRS | None"] = relationship("PembayaranKRS", back_populates="pendaftaran_krs", uselist=False)

    __mapper_args__ = {
        "polymorphic_identity": "krs",
    }

