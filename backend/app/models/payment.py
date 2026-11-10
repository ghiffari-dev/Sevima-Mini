from datetime import datetime
from sqlalchemy import Column, String, Float, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from app.models.base import Base

class Payment(Base):
    __tablename__ = "payments"

    idPayment = Column(String, primary_key=True, index=True)
    jumlah = Column(Float, nullable=False)
    tanggalBayar = Column(DateTime, nullable=True)
    statusBayar = Column(String, default="Pending")
    type = Column(String, nullable=False) # 'pmb', 'krs'

    __mapper_args__ = {
        "polymorphic_identity": "payment",
        "polymorphic_on": type,
    }

class PembayaranPMB(Payment):
    __tablename__ = "pembayaran_pmbs"

    idPayment = Column(String, ForeignKey("payments.idPayment"), primary_key=True)
    pendaftaran_pmb_id = Column(String, ForeignKey("pendaftaran_pmbs.idPendaftaran"), nullable=False)

    pendaftaran_pmb = relationship("PendaftaranPMB", back_populates="payment")

    __mapper_args__ = {
        "polymorphic_identity": "pmb_payment",
    }

class PembayaranKRS(Payment):
    __tablename__ = "pembayaran_krss"

    idPayment = Column(String, ForeignKey("payments.idPayment"), primary_key=True)
    pendaftaran_krs_id = Column(String, ForeignKey("pendaftaran_krss.idPendaftaran"), nullable=False)

    pendaftaran_krs = relationship("PendaftaranKRS", back_populates="payment")

    __mapper_args__ = {
        "polymorphic_identity": "krs_payment",
    }
