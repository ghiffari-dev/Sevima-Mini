from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import enum
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    select,
)
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.calon_mahasiswa import CalonMahasiswa
    from app.models.program_studi import ProgramStudi


class BillingStatus(str, enum.Enum):
    """Status siklus hidup tagihan SPP mahasiswa."""

    UNPAID = "unpaid"
    PARTIAL = "partial"
    PAID = "paid"
    OVERDUE = "overdue"


BILLING_TRANSITIONS: dict[BillingStatus, set[BillingStatus]] = {
    BillingStatus.UNPAID: {
        BillingStatus.PARTIAL,
        BillingStatus.PAID,
        BillingStatus.OVERDUE,
    },
    BillingStatus.PARTIAL: {
        BillingStatus.PARTIAL,
        BillingStatus.PAID,
        BillingStatus.OVERDUE,
    },
    BillingStatus.OVERDUE: {
        BillingStatus.OVERDUE,
        BillingStatus.PAID,
    },
    BillingStatus.PAID: set(),
}


class FinanceError(ValueError):
    """Exception dasar modul keuangan dengan status HTTP polimorfik."""

    status_code: int = 400

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        if status_code is not None:
            self.status_code = status_code

    def body(self) -> dict[str, Any]:
        return {"detail": str(self)}


class BillingNotFoundError(FinanceError):
    """Tagihan SPP tidak ditemukan (404)."""

    status_code: int = 404


class PaymentMethodNotFoundError(FinanceError):
    """Metode pembayaran tidak ditemukan atau tidak aktif (404)."""

    status_code: int = 404


class BillingAlreadyPaidError(FinanceError):
    """Tagihan sudah berstatus paid sehingga pembayaran ditolak (409)."""

    status_code: int = 409


class InvalidPaymentAmountError(FinanceError):
    """Nominal pembayaran tidak valid, misal <= 0 (422)."""

    status_code: int = 422


class WebhookSignatureError(FinanceError):
    """Signature webhook payment gateway tidak valid atau hilang (401)."""

    status_code: int = 401


DEFAULT_PAYMENT_METHODS: tuple[tuple[str, str, str], ...] = (
    ("VA_BCA", "Virtual Account BCA", "BCA"),
    ("VA_BNI", "Virtual Account BNI", "BNI"),
    ("QRIS", "QRIS Nasional", "QRIS"),
    ("BANK_TRANSFER", "Transfer Bank Manual", "BANK"),
    ("MANUAL_CASH", "Loket Keuangan Kampus", "CAMPUS"),
)


class PaymentMethod(Base):
    """Master metode pembayaran SPP yang didukung (VA, QRIS, Transfer, Tunai)."""

    __tablename__ = "payment_method"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    payments: Mapped[list["PaymentTransaction"]] = relationship(
        "PaymentTransaction", back_populates="payment_method"
    )


def seed_payment_methods(db: Session) -> list[PaymentMethod]:
    """Mengisi daftar metode pembayaran standar secara idempoten."""
    created_or_existing: list[PaymentMethod] = []
    for code, name, provider in DEFAULT_PAYMENT_METHODS:
        existing = db.scalars(
            select(PaymentMethod).where(PaymentMethod.code == code)
        ).first()
        if existing is None:
            existing = PaymentMethod(
                code=code, name=name, provider=provider, is_active=True
            )
            db.add(existing)
        created_or_existing.append(existing)
    db.flush()
    return created_or_existing


class Billing(Base):
    """Tagihan SPP per mahasiswa per semester dengan pelacakan status, denda, dan cicilan."""

    __tablename__ = "billing"
    __table_args__ = (
        UniqueConstraint("nim", "semester", name="uq_billing_nim_semester"),
        CheckConstraint("amount > 0", name="ck_billing_amount_positive"),
        CheckConstraint("late_fee >= 0", name="ck_billing_late_fee_non_negative"),
        CheckConstraint("amount_paid >= 0", name="ck_billing_amount_paid_non_negative"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    invoice_number: Mapped[str] = mapped_column(
        String(60), unique=True, nullable=False, index=True
    )
    nim: Mapped[str] = mapped_column(
        String(20), ForeignKey("calon_mahasiswa.nim"), nullable=False, index=True
    )
    semester: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    program_studi_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("program_studi.id"), nullable=False, index=True
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2, asdecimal=True), nullable=False
    )
    late_fee: Mapped[Decimal] = mapped_column(
        Numeric(14, 2, asdecimal=True), default=Decimal("0.00"), nullable=False
    )
    amount_paid: Mapped[Decimal] = mapped_column(
        Numeric(14, 2, asdecimal=True), default=Decimal("0.00"), nullable=False
    )
    due_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    status: Mapped[BillingStatus] = mapped_column(
        Enum(
            BillingStatus,
            values_callable=lambda x: [e.value for e in x],
            name="billingstatus",
        ),
        default=BillingStatus.UNPAID,
        nullable=False,
        index=True,
    )
    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_reminder_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    mahasiswa: Mapped["CalonMahasiswa"] = relationship("CalonMahasiswa")
    program_studi: Mapped["ProgramStudi"] = relationship("ProgramStudi")
    payments: Mapped[list["PaymentTransaction"]] = relationship(
        "PaymentTransaction",
        back_populates="billing",
        cascade="all, delete-orphan",
        order_by="PaymentTransaction.id",
    )

    @property
    def total_due(self) -> Decimal:
        """Total tagihan termasuk denda keterlambatan."""
        base = Decimal(str(self.amount or "0.00"))
        fee = Decimal(str(self.late_fee or "0.00"))
        return (base + fee).quantize(Decimal("0.01"))

    @property
    def remaining(self) -> Decimal:
        """Sisa kewajiban bayar (minimum 0.00)."""
        paid = Decimal(str(self.amount_paid or "0.00"))
        diff = self.total_due - paid
        return diff if diff > Decimal("0.00") else Decimal("0.00")

    @property
    def is_paid(self) -> bool:
        return self.status == BillingStatus.PAID

    def set_status(self, new_status: BillingStatus) -> BillingStatus:
        """Mengubah status billing sesuai matriks transisi sah."""
        if not isinstance(new_status, BillingStatus):
            new_status = BillingStatus(new_status)
        if new_status == self.status:
            return self.status
        allowed = BILLING_TRANSITIONS.get(self.status, set())
        if new_status not in allowed:
            raise FinanceError(
                f"Transisi status tagihan tidak diizinkan: {self.status.value} -> {new_status.value}",
                status_code=409,
            )
        self.status = new_status
        return self.status


class PaymentTransaction(Base):
    """Catatan transaksi pembayaran SPP (manual maupun otomatis via webhook)."""

    __tablename__ = "payment"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_payment_amount_positive"),
        CheckConstraint(
            "status IN ('pending', 'success', 'failed', 'refunded')",
            name="ck_payment_status_valid",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    billing_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("billing.id"), nullable=False, index=True
    )
    payment_method_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("payment_method.id"), nullable=False, index=True
    )
    transaction_id: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, index=True
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2, asdecimal=True), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), default="success", nullable=False)
    source: Mapped[str] = mapped_column(String(20), default="manual", nullable=False)
    paid_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    notes: Mapped[str | None] = mapped_column(String(300), nullable=True)
    raw_payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    billing: Mapped["Billing"] = relationship("Billing", back_populates="payments")
    payment_method: Mapped["PaymentMethod"] = relationship(
        "PaymentMethod", back_populates="payments"
    )
