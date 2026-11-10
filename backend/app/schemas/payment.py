from datetime import date, datetime
from pydantic import BaseModel, Field

class PaymentBase(BaseModel):
    jumlah: float = Field(..., gt=0)

class PaymentResponse(PaymentBase):
    idPayment: str
    tanggalBayar: datetime | None = None
    statusBayar: str = "Pending"

    class Config:
        from_attributes = True

class PembayaranPMBResponse(PaymentResponse):
    pendaftaran_pmb_id: str

class PembayaranKRSResponse(PaymentResponse):
    pendaftaran_krs_id: str

class VerifyPaymentRequest(BaseModel):
    status_bayar: str = Field(..., description="Lunas / Verified / Failed")
