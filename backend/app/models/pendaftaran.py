from datetime import datetime
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from app.models.base import Base

class Pendaftaran(Base):
    __tablename__ = "pendaftarans"

    idPendaftaran = Column(String, primary_key=True, index=True)
    tanggalDaftar = Column(DateTime, default=datetime.utcnow)
    status = Column(String, default="Pending")
    type = Column(String, nullable=False) # 'pmb', 'krs'

    __mapper_args__ = {
        "polymorphic_identity": "pendaftaran",
        "polymorphic_on": type,
    }

class PendaftaranPMB(Pendaftaran):
    __tablename__ = "pendaftaran_pmbs"

    idPendaftaran = Column(String, ForeignKey("pendaftarans.idPendaftaran"), primary_key=True)
    pilihanJurusan = Column(String, nullable=False)
    calon_mahasiswa_id = Column(Integer, ForeignKey("calon_mahasiswas.id"), nullable=False)

    calon_mahasiswa = relationship("CalonMahasiswa")
    payment = relationship("PembayaranPMB", back_populates="pendaftaran_pmb", uselist=False)

    __mapper_args__ = {
        "polymorphic_identity": "pmb",
    }

class PendaftaranKRS(Pendaftaran):
    __tablename__ = "pendaftaran_krss"

    idPendaftaran = Column(String, ForeignKey("pendaftarans.idPendaftaran"), primary_key=True)
    totalSks = Column(Integer, default=0)
    mahasiswa_id = Column(String, ForeignKey("mahasiswas.id"), nullable=False)

    mahasiswa = relationship("Mahasiswa", back_populates="pendaftaran_krs")
    enrollments = relationship("Enrollment", back_populates="pendaftaran_krs", cascade="all, delete-orphan")
    payment = relationship("PembayaranKRS", back_populates="pendaftaran_krs", uselist=False)

    __mapper_args__ = {
        "polymorphic_identity": "krs",
    }
