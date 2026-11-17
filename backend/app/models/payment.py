from datetime import datetime
from sqlalchemy import String, Float, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base

class Payment(Base):
    __tablename__ = "payments"

    idPayment: Mapped[str] = mapped_column(String(50), primary_key=True, index=True)
    jumlah: Mapped[float] = mapped_column(Float, nullable=False)
    tanggalBayar: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    statusBayar: Mapped[str] = mapped_column(String(30), default="Pending", nullable=False)
    type: Mapped[str] = mapped_column(String(30), nullable=False)  # 'pmb_payment', 'krs_payment'

    __mapper_args__ = {
        "polymorphic_identity": "payment",
        "polymorphic_on": type,
    }

class PembayaranPMB(Payment):
    __tablename__ = "pembayaran_pmbs"

    idPayment: Mapped[str] = mapped_column(String(50), ForeignKey("payments.idPayment"), primary_key=True)
    pendaftaran_pmb_id: Mapped[str] = mapped_column(String(50), ForeignKey("pendaftaran_pmbs.idPendaftaran"), nullable=False)

    pendaftaran_pmb: Mapped["PendaftaranPMB"] = relationship("PendaftaranPMB", back_populates="payment")

    __mapper_args__ = {
        "polymorphic_identity": "pmb_payment",
    }

class PembayaranKRS(Payment):
    __tablename__ = "pembayaran_krss"

    idPayment: Mapped[str] = mapped_column(String(50), ForeignKey("payments.idPayment"), primary_key=True)
    pendaftaran_krs_id: Mapped[str] = mapped_column(String(50), ForeignKey("pendaftaran_krss.idPendaftaran"), nullable=False)

    pendaftaran_krs: Mapped["PendaftaranKRS"] = relationship("PendaftaranKRS", back_populates="payment")

    __mapper_args__ = {
        "polymorphic_identity": "krs_payment",
    }

