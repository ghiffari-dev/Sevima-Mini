from sqlalchemy import String, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base

class Enrollment(Base):
    """Representasi baris detail pada kartu KRS (krs_detail).
    Status persetujuan tidak disimpan per baris, melainkan di kartu PendaftaranKRS.
    """
    __tablename__ = "enrollments"

    id_enrollment: Mapped[str] = mapped_column(String(50), primary_key=True, index=True)

    mahasiswa_id: Mapped[str] = mapped_column(String(50), ForeignKey("mahasiswas.id"), nullable=False)
    kelas_id: Mapped[str] = mapped_column(String(50), ForeignKey("kelass.id_kelas"), nullable=False)
    pendaftaran_krs_id: Mapped[str | None] = mapped_column(String(50), ForeignKey("pendaftaran_krss.idPendaftaran"), nullable=True)

    mahasiswa: Mapped["Mahasiswa"] = relationship("Mahasiswa", back_populates="enrollments")
    kelas: Mapped["Kelas"] = relationship("Kelas", back_populates="enrollments")
    pendaftaran_krs: Mapped["PendaftaranKRS | None"] = relationship("PendaftaranKRS", back_populates="enrollments")
    grade: Mapped["Grade | None"] = relationship("Grade", back_populates="enrollment", uselist=False, cascade="all, delete-orphan")

