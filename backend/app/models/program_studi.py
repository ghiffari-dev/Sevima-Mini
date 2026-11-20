from decimal import Decimal

from sqlalchemy import Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base

class ProgramStudi(Base):
    __tablename__ = "program_studi"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    kode: Mapped[str] = mapped_column(String(3), unique=True, nullable=False, index=True)
    nama: Mapped[str] = mapped_column(String(100), nullable=False)
    fakultas: Mapped[str] = mapped_column(String(100), nullable=False)
    biaya_spp: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 2, asdecimal=True), nullable=True
    )

    mahasiswa: Mapped[list["CalonMahasiswa"]] = relationship(back_populates="program_studi")
