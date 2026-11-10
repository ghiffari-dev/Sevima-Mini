from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base

class JalurMasuk(Base):
    __tablename__ = "jalur_masuk"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    nama: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)

    mahasiswa: Mapped[list["CalonMahasiswa"]] = relationship(back_populates="jalur_masuk")
