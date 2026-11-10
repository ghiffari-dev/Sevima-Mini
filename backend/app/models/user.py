from sqlalchemy import Column, String, ForeignKey
from sqlalchemy.orm import relationship
from app.models.base import Base

class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, index=True)
    nama = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(String, nullable=False)  # 'mahasiswa', 'dosen', 'admin', 'calon_mahasiswa'

    __mapper_args__ = {
        "polymorphic_identity": "user",
        "polymorphic_on": role,
    }

class Mahasiswa(User):
    __tablename__ = "mahasiswas"

    id = Column(String, ForeignKey("users.id"), primary_key=True)
    nim = Column(String, unique=True, index=True, nullable=False)
    jurusan = Column(String, nullable=False)

    enrollments = relationship("Enrollment", back_populates="mahasiswa")
    pendaftaran_krs = relationship("PendaftaranKRS", back_populates="mahasiswa")

    __mapper_args__ = {
        "polymorphic_identity": "mahasiswa",
    }

class Dosen(User):
    __tablename__ = "dosens"

    id = Column(String, ForeignKey("users.id"), primary_key=True)
    nip = Column(String, unique=True, index=True, nullable=False)
    keahlian = Column(String, nullable=False)

    kelas = relationship("Kelas", back_populates="dosen")

    __mapper_args__ = {
        "polymorphic_identity": "dosen",
    }

class Admin(User):
    __tablename__ = "admins"

    id = Column(String, ForeignKey("users.id"), primary_key=True)
    admin_role = Column(String, nullable=False)

    __mapper_args__ = {
        "polymorphic_identity": "admin",
    }
