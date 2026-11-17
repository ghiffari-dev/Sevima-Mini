from sqlalchemy import String, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base

class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(50), primary_key=True, index=True)
    nama: Mapped[str] = mapped_column(String(150), nullable=False)
    email: Mapped[str] = mapped_column(String(150), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(50), nullable=False)  # 'mahasiswa', 'dosen', 'admin', 'calon_mahasiswa'

    __mapper_args__ = {
        "polymorphic_identity": "user",
        "polymorphic_on": role,
    }

class Mahasiswa(User):
    __tablename__ = "mahasiswas"

    id: Mapped[str] = mapped_column(String(50), ForeignKey("users.id"), primary_key=True)
    nim: Mapped[str] = mapped_column(String(20), unique=True, index=True, nullable=False)
    jurusan: Mapped[str] = mapped_column(String(100), nullable=False)

    enrollments: Mapped[list["Enrollment"]] = relationship("Enrollment", back_populates="mahasiswa")
    pendaftaran_krs: Mapped[list["PendaftaranKRS"]] = relationship("PendaftaranKRS", back_populates="mahasiswa")

    __mapper_args__ = {
        "polymorphic_identity": "mahasiswa",
    }

class Dosen(User):
    __tablename__ = "dosens"

    id: Mapped[str] = mapped_column(String(50), ForeignKey("users.id"), primary_key=True)
    nip: Mapped[str] = mapped_column(String(30), unique=True, index=True, nullable=False)
    keahlian: Mapped[str] = mapped_column(String(100), nullable=False)

    kelas: Mapped[list["Kelas"]] = relationship("Kelas", back_populates="dosen")
    krs_bimbingan: Mapped[list["PendaftaranKRS"]] = relationship("PendaftaranKRS", back_populates="dosen_pa")

    __mapper_args__ = {
        "polymorphic_identity": "dosen",
    }

class Admin(User):
    __tablename__ = "admins"

    id: Mapped[str] = mapped_column(String(50), ForeignKey("users.id"), primary_key=True)
    admin_role: Mapped[str] = mapped_column(String(50), nullable=False)

    __mapper_args__ = {
        "polymorphic_identity": "admin",
    }

