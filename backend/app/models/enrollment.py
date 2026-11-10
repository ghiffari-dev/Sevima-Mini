from sqlalchemy import Column, String, ForeignKey
from sqlalchemy.orm import relationship
from app.models.base import Base

class Enrollment(Base):
    __tablename__ = "enrollments"

    id_enrollment = Column(String, primary_key=True, index=True)
    status = Column(String, default="Active")

    mahasiswa_id = Column(String, ForeignKey("mahasiswas.id"), nullable=False)
    kelas_id = Column(String, ForeignKey("kelass.id_kelas"), nullable=False)
    pendaftaran_krs_id = Column(String, ForeignKey("pendaftaran_krss.idPendaftaran"), nullable=True)

    mahasiswa = relationship("Mahasiswa", back_populates="enrollments")
    kelas = relationship("Kelas", back_populates="enrollments")
    pendaftaran_krs = relationship("PendaftaranKRS", back_populates="enrollments")
    grade = relationship("Grade", back_populates="enrollment", uselist=False, cascade="all, delete-orphan")
