from datetime import datetime, date
from sqlalchemy import DateTime, ForeignKey, Text, String, Date
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base

class CalonMahasiswa(Base):
    __tablename__ = "calon_mahasiswa"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    nama_lengkap: Mapped[str] = mapped_column(String(150), nullable=False)
    email: Mapped[str] = mapped_column(String(150), unique=True, nullable=False, index=True)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    tanggal_lahir: Mapped[date] = mapped_column(Date, nullable=False)
    alamat: Mapped[str | None] = mapped_column(Text, nullable=True)

    program_studi_id: Mapped[int] = mapped_column(ForeignKey("program_studi.id"), nullable=False)
    jalur_masuk_id: Mapped[int] = mapped_column(ForeignKey("jalur_masuk.id"), nullable=False)

    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    nim: Mapped[str | None] = mapped_column(String(20), unique=True, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    program_studi: Mapped["ProgramStudi"] = relationship(back_populates="mahasiswa")
    jalur_masuk: Mapped["JalurMasuk"] = relationship(back_populates="mahasiswa")
