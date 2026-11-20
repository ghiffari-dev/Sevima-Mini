from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import logging
from typing import Any, Protocol, runtime_checkable
import uuid

from sqlalchemy import func, inspect, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.models.calon_mahasiswa import CalonMahasiswa
from app.models.finance import (
    Billing,
    BillingAlreadyPaidError,
    BillingNotFoundError,
    BillingStatus,
    FinanceError,
    InvalidPaymentAmountError,
    PaymentMethod,
    PaymentMethodNotFoundError,
    PaymentTransaction,
    WebhookSignatureError,
    seed_payment_methods,
)
from app.models.krs import Notifikasi
from app.models.program_studi import ProgramStudi
from app.services.finance_calculator import (
    LateFeeConfig,
    PaymentCSVRow,
    ZERO,
    calculate_late_fee,
    compute_percentage,
    determine_billing_status,
    format_rupiah,
    quantize_money,
    resolve_spp_amount,
    to_decimal,
    verify_webhook_signature,
)
from app.services.schedule_observer import (
    LogChannel,
    NotificationChannel,
    NotificationRecord,
)

logger = logging.getLogger("finance.billing")

SUCCESS_WEBHOOK_STATUSES = frozenset(
    {"paid", "success", "settlement", "capture", "completed"}
)
NON_SUCCESS_WEBHOOK_STATUSES = frozenset(
    {"failed", "expired", "pending", "cancelled", "deny"}
)

finance_notification_history: deque[NotificationRecord] = deque(maxlen=250)
default_finance_email_channel = LogChannel(
    "EMAIL", history=finance_notification_history
)


@runtime_checkable
class BillingGuardPort(Protocol):
    """Port Dependency Inversion untuk memeriksa tunggakan SPP sebelum pengisian KRS."""

    def get_unpaid_billings(self, nim: str) -> list[Billing]:
        ...


class SQLAlchemyBillingGuard:
    """Implementasi BillingGuardPort berbasis SQLAlchemy."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def get_unpaid_billings(self, nim: str) -> list[Billing]:
        """Mengembalikan seluruh tagihan SPP mahasiswa yang belum berstatus `paid`."""
        conn = self.db.connection()
        if not inspect(conn).has_table(Billing.__tablename__):
            return []
        stmt = (
            select(Billing)
            .where(Billing.nim == nim, Billing.status != BillingStatus.PAID)
            .order_by(Billing.due_date.asc(), Billing.id.asc())
        )
        return list(self.db.scalars(stmt).all())


@dataclass(frozen=True)
class GenerateBillingResult:
    """Hasil eksekusi generator tagihan SPP per semester."""

    semester: str
    semester_start: date
    due_date: date
    created_count: int
    skipped_count: int
    created_billings: tuple[Billing, ...]


@dataclass(frozen=True)
class PaymentResult:
    """Hasil eksekusi pemrosesan pembayaran (manual maupun webhook)."""

    billing: Billing
    payment: PaymentTransaction
    previous_status: BillingStatus
    new_status: BillingStatus
    overpayment: Decimal
    idempotent_replay: bool
    receipt_record: NotificationRecord | None


@dataclass(frozen=True)
class WebhookResult:
    """Hasil penanganan webhook payment gateway."""

    transaction_id: str
    billing_id: int
    invoice_number: str
    gateway_status: str
    billing_status: BillingStatus
    processed_payment: bool
    idempotent_replay: bool
    message: str
    payment_result: PaymentResult | None = None


@dataclass(frozen=True)
class ReminderJobResult:
    """Hasil job harian pembaruan status overdue, denda, dan pengingat SPP."""

    as_of: date
    overdue_updated: int
    late_fees_applied: int
    reminders_sent: int
    receipts: tuple[NotificationRecord, ...]


class BillingService:
    """Layanan satu pintu untuk penagihan SPP, pembayaran atomik, webhook, reminder, & dashboard."""

    def __init__(
        self,
        db: Session,
        email_channel: NotificationChannel | None = None,
        late_fee_config: LateFeeConfig | None = None,
        webhook_secret: str | None = None,
    ) -> None:
        self.db = db
        self.email_channel = email_channel or default_finance_email_channel
        self.late_fee_config = late_fee_config or LateFeeConfig.from_settings()
        self.webhook_secret = (
            webhook_secret
            if webhook_secret is not None
            else settings.PAYMENT_WEBHOOK_SECRET
        )

    def ensure_payment_methods(self) -> list[PaymentMethod]:
        """Memastikan master metode pembayaran standar tersedia."""
        methods = seed_payment_methods(self.db)
        self.db.commit()
        return methods

    def generate_billing(
        self,
        semester: str,
        semester_start: date | None = None,
    ) -> GenerateBillingResult:
        """Membuat tagihan SPP awal semester untuk seluruh mahasiswa aktif secara idempoten."""
        semester_clean = semester.strip()
        if not semester_clean:
            raise FinanceError("Kode semester wajib diisi", status_code=422)

        start_date = semester_start or date.today()
        due_date = start_date + timedelta(days=int(settings.SPP_DUE_DAYS))

        try:
            seed_payment_methods(self.db)

            stmt_students = (
                select(CalonMahasiswa)
                .where(
                    CalonMahasiswa.status == "approved",
                    CalonMahasiswa.nim.is_not(None),
                )
                .options(selectinload(CalonMahasiswa.program_studi))
                .order_by(CalonMahasiswa.id.asc())
            )
            students = list(self.db.scalars(stmt_students).all())

            existing_nims = set(
                self.db.scalars(
                    select(Billing.nim).where(Billing.semester == semester_clean)
                ).all()
            )

            created: list[Billing] = []
            skipped = 0
            for mhs in students:
                if not mhs.nim or mhs.nim in existing_nims:
                    skipped += 1
                    continue

                prodi = mhs.program_studi
                spp_amount = resolve_spp_amount(
                    prodi.nama if prodi else "",
                    prodi.fakultas if prodi else "",
                    prodi.biaya_spp if prodi else None,
                )
                invoice_number = f"INV-{semester_clean}-{mhs.nim}"
                billing = Billing(
                    invoice_number=invoice_number,
                    nim=mhs.nim,
                    semester=semester_clean,
                    program_studi_id=mhs.program_studi_id,
                    amount=spp_amount,
                    late_fee=ZERO,
                    amount_paid=ZERO,
                    due_date=due_date,
                    status=BillingStatus.UNPAID,
                )
                self.db.add(billing)
                self.db.add(
                    Notifikasi(
                        nim=mhs.nim,
                        pesan=(
                            f"Tagihan SPP semester {semester_clean} sebesar "
                            f"{format_rupiah(spp_amount)} telah terbit "
                            f"(jatuh tempo {due_date.isoformat()})."
                        ),
                    )
                )
                created.append(billing)
                existing_nims.add(mhs.nim)

            self.db.commit()
            for item in created:
                self.db.refresh(item)
            return GenerateBillingResult(
                semester=semester_clean,
                semester_start=start_date,
                due_date=due_date,
                created_count=len(created),
                skipped_count=skipped,
                created_billings=tuple(created),
            )
        except Exception:
            self.db.rollback()
            raise

    def process_payment(
        self,
        billing_id: int,
        amount: Decimal | int | str,
        method_code: str,
        *,
        transaction_id: str | None = None,
        source: str = "manual",
        paid_at: datetime | None = None,
        notes: str | None = None,
        raw_payload: str | None = None,
        as_of: date | None = None,
    ) -> PaymentResult:
        """Memproses pembayaran SPP secara atomik (validasi, penguncian baris, cicilan kumulatif, receipt)."""
        try:
            amount_dec = quantize_money(to_decimal(amount))
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise InvalidPaymentAmountError("Nominal pembayaran tidak valid") from exc

        if amount_dec <= ZERO:
            raise InvalidPaymentAmountError("Nominal pembayaran harus lebih besar dari 0")

        tx_id = (transaction_id or "").strip() or f"TX-{uuid.uuid4().hex[:16].upper()}"

        existing_tx = self.db.scalars(
            select(PaymentTransaction)
            .where(PaymentTransaction.transaction_id == tx_id)
            .options(selectinload(PaymentTransaction.billing))
        ).first()
        if existing_tx is not None and existing_tx.status == "success":
            return PaymentResult(
                billing=existing_tx.billing,
                payment=existing_tx,
                previous_status=existing_tx.billing.status,
                new_status=existing_tx.billing.status,
                overpayment=ZERO,
                idempotent_replay=True,
                receipt_record=None,
            )

        receipt_email: str | None = None
        receipt_message: str = ""
        try:
            billing = self.db.scalars(
                select(Billing)
                .where(Billing.id == billing_id)
                .options(selectinload(Billing.mahasiswa))
                .with_for_update()
            ).first()
            if billing is None:
                raise BillingNotFoundError(
                    f"Tagihan dengan ID {billing_id} tidak ditemukan"
                )

            if billing.status == BillingStatus.PAID:
                raise BillingAlreadyPaidError(
                    f"Tagihan {billing.invoice_number} sudah berstatus paid"
                )

            method_norm = method_code.strip().upper()
            method = self.db.scalars(
                select(PaymentMethod).where(
                    func.upper(PaymentMethod.code) == method_norm,
                    PaymentMethod.is_active.is_(True),
                )
            ).first()
            if method is None:
                raise PaymentMethodNotFoundError(
                    f"Metode pembayaran '{method_code}' tidak ditemukan atau tidak aktif"
                )

            tx_dt = paid_at or datetime.now(timezone.utc)
            ref_date = as_of or tx_dt.date()

            computed_fee = calculate_late_fee(
                billing.amount,
                billing.due_date,
                ref_date,
                billing.status,
                self.late_fee_config,
            )
            current_fee = quantize_money(to_decimal(billing.late_fee))
            if computed_fee > current_fee:
                billing.late_fee = computed_fee

            total_due = billing.total_due
            prev_paid = quantize_money(to_decimal(billing.amount_paid))
            new_total_paid = quantize_money(prev_paid + amount_dec)
            overpayment = (
                quantize_money(new_total_paid - total_due)
                if new_total_paid > total_due
                else ZERO
            )

            prev_status = billing.status
            new_status = determine_billing_status(
                total_due, new_total_paid, billing.due_date, ref_date
            )

            billing.amount_paid = new_total_paid
            billing.set_status(new_status)
            if new_status == BillingStatus.PAID and billing.paid_at is None:
                billing.paid_at = tx_dt

            payment = PaymentTransaction(
                billing_id=billing.id,
                payment_method_id=method.id,
                transaction_id=tx_id,
                amount=amount_dec,
                status="success",
                source=source,
                paid_at=tx_dt,
                notes=notes,
                raw_payload=raw_payload,
            )
            self.db.add(payment)

            receipt_message = (
                f"Kwitansi Pembayaran SPP {billing.invoice_number}: "
                f"diterima {format_rupiah(amount_dec)} via {method.code} "
                f"(status: {new_status.value}, sisa: {format_rupiah(billing.remaining)})."
            )
            self.db.add(Notifikasi(nim=billing.nim, pesan=receipt_message))

            receipt_email = (
                billing.mahasiswa.email
                if billing.mahasiswa and billing.mahasiswa.email
                else f"{billing.nim}@student.sevima.ac.id"
            )

            self.db.commit()
            self.db.refresh(billing)
            self.db.refresh(payment)
        except Exception:
            self.db.rollback()
            raise

        receipt_rec = self.email_channel.send(
            recipient=receipt_email,
            message=receipt_message,
            key=f"receipt:{payment.transaction_id}",
            observer="BillingService",
            event_type="PAYMENT_RECEIPT",
        )
        logger.info(
            "Payment recorded: tx=%s invoice=%s amount=%s status=%s->%s",
            payment.transaction_id,
            billing.invoice_number,
            amount_dec,
            prev_status.value,
            new_status.value,
        )
        return PaymentResult(
            billing=billing,
            payment=payment,
            previous_status=prev_status,
            new_status=new_status,
            overpayment=overpayment,
            idempotent_replay=False,
            receipt_record=receipt_rec,
        )

    def handle_webhook(
        self,
        raw_body: bytes,
        signature: str | None,
        payload: dict[str, Any],
    ) -> WebhookResult:
        """Memverifikasi signature webhook, mengekstrak transaksi, dan memproses pembayaran atomik."""
        if not verify_webhook_signature(raw_body, signature, self.webhook_secret):
            raise WebhookSignatureError("Signature webhook tidak valid atau hilang")

        transaction_id = str(payload.get("transaction_id") or "").strip()
        if not transaction_id:
            raise FinanceError(
                "transaction_id wajib ada pada payload webhook", status_code=422
            )

        raw_status = str(payload.get("status") or "").strip().lower()
        if not raw_status:
            raise FinanceError(
                "status wajib ada pada payload webhook", status_code=422
            )

        method_code = str(
            payload.get("payment_method") or payload.get("method_code") or "VA_BCA"
        ).strip().upper()

        billing = self._resolve_billing_from_webhook(payload)

        if payload.get("amount") is None:
            raise InvalidPaymentAmountError(
                "Nominal amount wajib ada pada payload webhook"
            )

        paid_at_dt: datetime | None = None
        if payload.get("paid_at"):
            try:
                paid_at_dt = datetime.fromisoformat(str(payload["paid_at"]))
                if paid_at_dt.tzinfo is None:
                    paid_at_dt = paid_at_dt.replace(tzinfo=timezone.utc)
            except ValueError as exc:
                raise FinanceError(
                    "Format paid_at webhook harus ISO-8601", status_code=422
                ) from exc

        if raw_status in SUCCESS_WEBHOOK_STATUSES:
            pay_res = self.process_payment(
                billing.id,
                payload["amount"],
                method_code,
                transaction_id=transaction_id,
                source="webhook",
                paid_at=paid_at_dt,
                notes=f"Gateway webhook ({raw_status})",
                raw_payload=raw_body.decode("utf-8", errors="replace"),
                as_of=paid_at_dt.date() if paid_at_dt else None,
            )
            msg = (
                "Webhook duplikat (idempoten): transaksi sudah pernah diproses"
                if pay_res.idempotent_replay
                else f"Webhook diterima: status tagihan {pay_res.new_status.value}"
            )
            return WebhookResult(
                transaction_id=transaction_id,
                billing_id=pay_res.billing.id,
                invoice_number=pay_res.billing.invoice_number,
                gateway_status=raw_status,
                billing_status=pay_res.new_status,
                processed_payment=True,
                idempotent_replay=pay_res.idempotent_replay,
                message=msg,
                payment_result=pay_res,
            )

        if raw_status in NON_SUCCESS_WEBHOOK_STATUSES:
            return self._record_non_success_webhook(
                billing=billing,
                transaction_id=transaction_id,
                amount=payload["amount"],
                method_code=method_code,
                raw_status=raw_status,
                raw_body=raw_body,
                paid_at=paid_at_dt,
            )

        raise FinanceError(
            f"Status webhook tidak dikenal: '{raw_status}'", status_code=422
        )

    def _resolve_billing_from_webhook(self, payload: dict[str, Any]) -> Billing:
        """Mencari target Billing dari payload webhook berdasarkan billing_id, invoice_number, atau nim+semester."""
        if payload.get("billing_id") is not None:
            try:
                bid = int(payload["billing_id"])
            except (TypeError, ValueError) as exc:
                raise FinanceError("billing_id harus berupa integer", status_code=422) from exc
            billing = self.db.get(Billing, bid)
        elif payload.get("invoice_number"):
            inv = str(payload["invoice_number"]).strip()
            billing = self.db.scalars(
                select(Billing).where(Billing.invoice_number == inv)
            ).first()
        elif payload.get("nim") and payload.get("semester"):
            billing = self.db.scalars(
                select(Billing).where(
                    Billing.nim == str(payload["nim"]).strip(),
                    Billing.semester == str(payload["semester"]).strip(),
                )
            ).first()
        else:
            raise FinanceError(
                "Payload webhook wajib menyertakan billing_id, invoice_number, atau nim+semester",
                status_code=422,
            )

        if billing is None:
            raise BillingNotFoundError("Tagihan SPP untuk webhook tidak ditemukan")
        return billing

    def _record_non_success_webhook(
        self,
        *,
        billing: Billing,
        transaction_id: str,
        amount: Decimal | int | str,
        method_code: str,
        raw_status: str,
        raw_body: bytes,
        paid_at: datetime | None,
    ) -> WebhookResult:
        """Mencatat event webhook gagal/pending secara idempoten tanpa mengubah saldo tagihan."""
        try:
            amount_dec = quantize_money(to_decimal(amount))
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise InvalidPaymentAmountError("Nominal amount webhook tidak valid") from exc
        if amount_dec <= ZERO:
            raise InvalidPaymentAmountError("Nominal amount webhook harus lebih dari 0")

        existing_tx = self.db.scalars(
            select(PaymentTransaction).where(
                PaymentTransaction.transaction_id == transaction_id
            )
        ).first()
        if existing_tx is not None:
            return WebhookResult(
                transaction_id=transaction_id,
                billing_id=billing.id,
                invoice_number=billing.invoice_number,
                gateway_status=raw_status,
                billing_status=billing.status,
                processed_payment=False,
                idempotent_replay=True,
                message="Webhook non-sukses duplikat (idempoten)",
                payment_result=None,
            )

        normalized_tx_status = "pending" if raw_status == "pending" else "failed"
        try:
            method = self.db.scalars(
                select(PaymentMethod).where(
                    func.upper(PaymentMethod.code) == method_code
                )
            ).first()
            if method is None:
                raise PaymentMethodNotFoundError(
                    f"Metode pembayaran '{method_code}' tidak ditemukan"
                )
            tx = PaymentTransaction(
                billing_id=billing.id,
                payment_method_id=method.id,
                transaction_id=transaction_id,
                amount=amount_dec,
                status=normalized_tx_status,
                source="webhook",
                paid_at=paid_at or datetime.now(timezone.utc),
                notes=f"Gateway webhook ({raw_status})",
                raw_payload=raw_body.decode("utf-8", errors="replace"),
            )
            self.db.add(tx)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

        return WebhookResult(
            transaction_id=transaction_id,
            billing_id=billing.id,
            invoice_number=billing.invoice_number,
            gateway_status=raw_status,
            billing_status=billing.status,
            processed_payment=False,
            idempotent_replay=False,
            message=f"Webhook status '{raw_status}' dicatat tanpa mengubah saldo tagihan",
            payment_result=None,
        )

    def refresh_overdue_and_send_reminders(
        self,
        as_of: date | None = None,
        reminder_before_days: int = 3,
    ) -> ReminderJobResult:
        """Memperbarui denda + status overdue serta mengirim reminder otomatis H-N & tunggakan."""
        ref_date = as_of or date.today()
        pending_emails: list[tuple[str, str, str]] = []
        overdue_updated = 0
        late_fees_applied = 0

        try:
            stmt = (
                select(Billing)
                .where(Billing.status != BillingStatus.PAID)
                .options(selectinload(Billing.mahasiswa))
                .with_for_update()
            )
            billings = list(self.db.scalars(stmt).all())

            for b in billings:
                new_fee = calculate_late_fee(
                    b.amount,
                    b.due_date,
                    ref_date,
                    b.status,
                    self.late_fee_config,
                )
                current_fee = quantize_money(to_decimal(b.late_fee))
                if new_fee > current_fee:
                    b.late_fee = new_fee
                    late_fees_applied += 1

                if ref_date > b.due_date and b.status != BillingStatus.OVERDUE:
                    b.set_status(BillingStatus.OVERDUE)
                    overdue_updated += 1

                days_until_due = (b.due_date - ref_date).days
                needs_reminder = (
                    b.status == BillingStatus.OVERDUE
                    or 0 <= days_until_due <= reminder_before_days
                )
                already_sent_today = (
                    b.last_reminder_at is not None
                    and b.last_reminder_at.date() == ref_date
                )
                if needs_reminder and not already_sent_today:
                    b.last_reminder_at = datetime.now(timezone.utc)
                    msg = (
                        f"Reminder SPP {b.invoice_number}: tagihan status {b.status.value}, "
                        f"sisa {format_rupiah(b.remaining)} (jatuh tempo {b.due_date.isoformat()})."
                    )
                    self.db.add(Notifikasi(nim=b.nim, pesan=msg))
                    recipient = (
                        b.mahasiswa.email
                        if b.mahasiswa and b.mahasiswa.email
                        else f"{b.nim}@student.sevima.ac.id"
                    )
                    pending_emails.append(
                        (recipient, msg, f"reminder:{b.id}:{ref_date.isoformat()}")
                    )

            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

        sent_records: list[NotificationRecord] = []
        for recipient, msg, key in pending_emails:
            rec = self.email_channel.send(
                recipient=recipient,
                message=msg,
                key=key,
                observer="FinanceScheduler",
                event_type="PAYMENT_REMINDER",
            )
            if rec is not None:
                sent_records.append(rec)

        return ReminderJobResult(
            as_of=ref_date,
            overdue_updated=overdue_updated,
            late_fees_applied=late_fees_applied,
            reminders_sent=len(sent_records),
            receipts=tuple(sent_records),
        )

    def list_billings(
        self,
        *,
        nim: str | None = None,
        semester: str | None = None,
        status_filter: BillingStatus | str | None = None,
    ) -> list[dict[str, Any]]:
        """Mengembalikan daftar detail tagihan SPP terstruktur."""
        stmt = (
            select(Billing)
            .options(
                selectinload(Billing.mahasiswa),
                selectinload(Billing.program_studi),
            )
            .order_by(Billing.due_date.desc(), Billing.id.desc())
        )
        if nim:
            stmt = stmt.where(Billing.nim == nim.strip())
        if semester:
            stmt = stmt.where(Billing.semester == semester.strip())
        if status_filter:
            st_val = (
                status_filter
                if isinstance(status_filter, BillingStatus)
                else BillingStatus(str(status_filter).lower())
            )
            stmt = stmt.where(Billing.status == st_val)

        rows: list[dict[str, Any]] = []
        for b in self.db.scalars(stmt).all():
            rows.append(
                {
                    "id": b.id,
                    "invoice_number": b.invoice_number,
                    "nim": b.nim,
                    "nama_mahasiswa": b.mahasiswa.nama_lengkap if b.mahasiswa else b.nim,
                    "semester": b.semester,
                    "program_studi_id": b.program_studi_id,
                    "program_studi_nama": b.program_studi.nama if b.program_studi else "-",
                    "amount": f"{quantize_money(to_decimal(b.amount)):.2f}",
                    "late_fee": f"{quantize_money(to_decimal(b.late_fee)):.2f}",
                    "total_tagihan": f"{b.total_due:.2f}",
                    "sudah_bayar": f"{quantize_money(to_decimal(b.amount_paid)):.2f}",
                    "sisa": f"{b.remaining:.2f}",
                    "due_date": b.due_date,
                    "status": b.status.value,
                    "krs_blocked": b.status != BillingStatus.PAID,
                    "paid_at": b.paid_at,
                }
            )
        return rows

    def get_student_summary(
        self,
        nim: str | None = None,
        semester: str | None = None,
    ) -> list[dict[str, Any]]:
        """Menghitung total tagihan, sudah bayar, sisa, dan status blokir KRS per mahasiswa."""
        stmt = (
            select(Billing)
            .options(
                selectinload(Billing.mahasiswa),
                selectinload(Billing.program_studi),
            )
            .order_by(Billing.nim.asc(), Billing.id.asc())
        )
        if nim:
            stmt = stmt.where(Billing.nim == nim.strip())
        if semester:
            stmt = stmt.where(Billing.semester == semester.strip())

        grouped: dict[str, dict[str, Any]] = {}
        for b in self.db.scalars(stmt).all():
            entry = grouped.get(b.nim)
            if entry is None:
                entry = {
                    "nim": b.nim,
                    "nama_mahasiswa": b.mahasiswa.nama_lengkap if b.mahasiswa else b.nim,
                    "program_studi": b.program_studi.nama if b.program_studi else "-",
                    "total_tagihan": ZERO,
                    "sudah_bayar": ZERO,
                    "sisa": ZERO,
                    "krs_blocked": False,
                    "statuses": [],
                    "latest_billing_id": b.id,
                    "latest_invoice_number": b.invoice_number,
                    "latest_due_date": b.due_date,
                }
                grouped[b.nim] = entry

            entry["total_tagihan"] += b.total_due
            entry["sudah_bayar"] += quantize_money(to_decimal(b.amount_paid))
            entry["sisa"] += b.remaining
            if b.status != BillingStatus.PAID:
                entry["krs_blocked"] = True
            entry["statuses"].append(b.status.value)
            entry["latest_billing_id"] = b.id
            entry["latest_invoice_number"] = b.invoice_number
            entry["latest_due_date"] = b.due_date

        result: list[dict[str, Any]] = []
        for entry in grouped.values():
            statuses = entry.pop("statuses")
            if "overdue" in statuses:
                agg_status = "overdue"
            elif "partial" in statuses:
                agg_status = "partial"
            elif "unpaid" in statuses:
                agg_status = "unpaid"
            else:
                agg_status = "paid"

            result.append(
                {
                    "nim": entry["nim"],
                    "nama_mahasiswa": entry["nama_mahasiswa"],
                    "program_studi": entry["program_studi"],
                    "total_tagihan": f"{quantize_money(entry['total_tagihan']):.2f}",
                    "sudah_bayar": f"{quantize_money(entry['sudah_bayar']):.2f}",
                    "sisa": f"{quantize_money(entry['sisa']):.2f}",
                    "status": agg_status,
                    "krs_blocked": entry["krs_blocked"],
                    "latest_billing_id": entry["latest_billing_id"],
                    "latest_invoice_number": entry["latest_invoice_number"],
                    "latest_due_date": entry["latest_due_date"],
                }
            )
        return result

    def get_prodi_collection_rates(
        self,
        semester: str | None = None,
    ) -> list[dict[str, Any]]:
        """Menghitung collection rate dan agregasi tagihan per program studi."""
        stmt = select(Billing).options(selectinload(Billing.program_studi))
        if semester:
            stmt = stmt.where(Billing.semester == semester.strip())

        by_prodi: dict[int, dict[str, Any]] = {}
        for b in self.db.scalars(stmt).all():
            pid = b.program_studi_id
            bucket = by_prodi.get(pid)
            if bucket is None:
                bucket = {
                    "program_studi_id": pid,
                    "kode_prodi": b.program_studi.kode if b.program_studi else "-",
                    "nama_prodi": b.program_studi.nama if b.program_studi else "-",
                    "fakultas": b.program_studi.fakultas if b.program_studi else "-",
                    "total_tagihan_count": 0,
                    "lunas_count": 0,
                    "total_billed": ZERO,
                    "total_collected": ZERO,
                    "total_outstanding": ZERO,
                }
                by_prodi[pid] = bucket

            bucket["total_tagihan_count"] += 1
            if b.status == BillingStatus.PAID:
                bucket["lunas_count"] += 1
            bucket["total_billed"] += b.total_due
            bucket["total_collected"] += min(
                b.total_due, quantize_money(to_decimal(b.amount_paid))
            )
            bucket["total_outstanding"] += b.remaining

        items: list[dict[str, Any]] = []
        for bucket in sorted(by_prodi.values(), key=lambda x: x["kode_prodi"]):
            rate = compute_percentage(
                bucket["lunas_count"], bucket["total_tagihan_count"]
            )
            items.append(
                {
                    "program_studi_id": bucket["program_studi_id"],
                    "kode_prodi": bucket["kode_prodi"],
                    "nama_prodi": bucket["nama_prodi"],
                    "fakultas": bucket["fakultas"],
                    "total_tagihan_count": bucket["total_tagihan_count"],
                    "lunas_count": bucket["lunas_count"],
                    "collection_rate": f"{rate:.2f}",
                    "total_billed": f"{quantize_money(bucket['total_billed']):.2f}",
                    "total_collected": f"{quantize_money(bucket['total_collected']):.2f}",
                    "total_outstanding": f"{quantize_money(bucket['total_outstanding']):.2f}",
                }
            )
        return items

    def get_monthly_payments(self, year: int | None = None) -> list[dict[str, Any]]:
        """Mengagregasi pembayaran sukses per bulan (YYYY-MM) untuk grafik dashboard."""
        stmt = (
            select(PaymentTransaction)
            .where(PaymentTransaction.status == "success")
            .order_by(PaymentTransaction.paid_at.asc())
        )
        monthly_totals: dict[str, Decimal] = defaultdict(lambda: ZERO)
        monthly_counts: dict[str, int] = defaultdict(int)

        for tx in self.db.scalars(stmt).all():
            if year is not None and tx.paid_at.year != year:
                continue
            month_key = tx.paid_at.strftime("%Y-%m")
            monthly_totals[month_key] += quantize_money(to_decimal(tx.amount))
            monthly_counts[month_key] += 1

        return [
            {
                "month": month_key,
                "total_amount": f"{quantize_money(monthly_totals[month_key]):.2f}",
                "transaction_count": monthly_counts[month_key],
            }
            for month_key in sorted(monthly_totals.keys())
        ]

    def get_dashboard_overview(
        self,
        semester: str | None = None,
    ) -> dict[str, Any]:
        """Menggabungkan seluruh ringkasan real-time untuk Dashboard Keuangan."""
        students = self.get_student_summary(semester=semester)
        prodi_rates = self.get_prodi_collection_rates(semester=semester)
        monthly = self.get_monthly_payments()

        total_billed = sum(
            (Decimal(s["total_tagihan"]) for s in students), start=ZERO
        )
        total_collected = sum(
            (Decimal(s["sudah_bayar"]) for s in students), start=ZERO
        )
        total_outstanding = sum(
            (Decimal(s["sisa"]) for s in students), start=ZERO
        )
        lunas_students = sum(1 for s in students if not s["krs_blocked"])
        overall_rate = compute_percentage(lunas_students, len(students))

        return {
            "semester": semester or "ALL",
            "total_mahasiswa": len(students),
            "mahasiswa_lunas": lunas_students,
            "mahasiswa_menunggak": len(students) - lunas_students,
            "overall_collection_rate": f"{overall_rate:.2f}",
            "total_tagihan": f"{quantize_money(total_billed):.2f}",
            "total_terbayar": f"{quantize_money(total_collected):.2f}",
            "total_tunggakan": f"{quantize_money(total_outstanding):.2f}",
            "students": students,
            "per_prodi": prodi_rates,
            "monthly_payments": monthly,
        }

    def export_payment_csv_rows(
        self,
        semester: str | None = None,
    ) -> list[PaymentCSVRow]:
        """Mengekspor data pembayaran & tunggakan DB menjadi daftar PaymentCSVRow untuk AI Report."""
        rows: list[PaymentCSVRow] = []

        tx_stmt = (
            select(PaymentTransaction)
            .join(Billing, PaymentTransaction.billing_id == Billing.id)
            .options(selectinload(PaymentTransaction.billing))
            .where(PaymentTransaction.status == "success")
        )
        if semester:
            tx_stmt = tx_stmt.where(Billing.semester == semester.strip())

        for tx in self.db.scalars(tx_stmt).all():
            rows.append(
                PaymentCSVRow(
                    nim=tx.billing.nim,
                    jumlah=quantize_money(to_decimal(tx.amount)),
                    tanggal=tx.paid_at.date(),
                    status="paid",
                )
            )

        bill_stmt = select(Billing).where(Billing.status != BillingStatus.PAID)
        if semester:
            bill_stmt = bill_stmt.where(Billing.semester == semester.strip())

        for b in self.db.scalars(bill_stmt).all():
            rem = b.remaining
            if rem > ZERO:
                rows.append(
                    PaymentCSVRow(
                        nim=b.nim,
                        jumlah=rem,
                        tanggal=b.due_date,
                        status=b.status.value,
                        sisa=rem,
                        due_date=b.due_date,
                    )
                )
        return rows

    def seed_demo_data(self, semester: str = "20251") -> dict[str, Any]:
        """Memuat skenario demo Minggu 11 (Teknik 5jt, Ekonomi 4jt, cicilan, overdue >2 bulan)."""
        try:
            seed_payment_methods(self.db)

            prodi_ti = self.db.scalars(
                select(ProgramStudi).where(ProgramStudi.kode == "001")
            ).first()
            if prodi_ti is None:
                prodi_ti = ProgramStudi(
                    kode="001",
                    nama="Teknik Informatika",
                    fakultas="Fakultas Teknik",
                    biaya_spp=Decimal("5000000.00"),
                )
                self.db.add(prodi_ti)

            prodi_ek = self.db.scalars(
                select(ProgramStudi).where(ProgramStudi.kode == "002")
            ).first()
            if prodi_ek is None:
                prodi_ek = ProgramStudi(
                    kode="002",
                    nama="Manajemen Ekonomi",
                    fakultas="Fakultas Ekonomi",
                    biaya_spp=Decimal("4000000.00"),
                )
                self.db.add(prodi_ek)

            from app.models.jalur_masuk import JalurMasuk

            jalur = self.db.scalars(
                select(JalurMasuk).where(JalurMasuk.nama == "SNBP")
            ).first()
            if jalur is None:
                jalur = JalurMasuk(nama="SNBP")
                self.db.add(jalur)
            self.db.flush()

            demo_students = [
                ("2025001-0101", "Andi Pratama", "andi.fin@sevima.ac.id", prodi_ti.id),
                ("2025001-0102", "Siti Rahma", "siti.fin@sevima.ac.id", prodi_ti.id),
                ("2025001-0103", "Bima Sakti", "bima.fin@sevima.ac.id", prodi_ek.id),
                ("2025001-0104", "Dewi Lestari", "dewi.fin@sevima.ac.id", prodi_ek.id),
                ("2025001-0105", "Farhan Nugroho", "farhan.fin@sevima.ac.id", prodi_ti.id),
            ]
            for nim, nama, email, pid in demo_students:
                existing_mhs = self.db.scalars(
                    select(CalonMahasiswa).where(CalonMahasiswa.nim == nim)
                ).first()
                if existing_mhs is None:
                    self.db.add(
                        CalonMahasiswa(
                            nama_lengkap=nama,
                            email=email,
                            phone="081200000000",
                            tanggal_lahir=date(2005, 5, 10),
                            program_studi_id=pid,
                            jalur_masuk_id=jalur.id,
                            status="approved",
                            nim=nim,
                        )
                    )
            self.db.flush()

            today = date.today()
            gen = self.generate_billing(
                semester=semester,
                semester_start=today - timedelta(days=3),
            )

            # Atur skenario status beragam pada tagihan demo jika belum pernah dibayar
            b_paid = self.db.scalars(
                select(Billing).where(
                    Billing.nim == "2025001-0101", Billing.semester == semester
                )
            ).first()
            if b_paid and b_paid.status == BillingStatus.UNPAID:
                self.process_payment(
                    b_paid.id,
                    b_paid.amount,
                    "VA_BCA",
                    transaction_id=f"DEMO-PAID-{semester}",
                    source="webhook",
                    notes="Demo pembayaran lunas",
                )

            b_partial = self.db.scalars(
                select(Billing).where(
                    Billing.nim == "2025001-0103", Billing.semester == semester
                )
            ).first()
            if b_partial and b_partial.status == BillingStatus.UNPAID:
                self.process_payment(
                    b_partial.id,
                    Decimal("2000000.00"),
                    "QRIS",
                    transaction_id=f"DEMO-PARTIAL-{semester}",
                    source="manual",
                    notes="Demo cicilan tahap 1",
                )

            b_overdue = self.db.scalars(
                select(Billing).where(
                    Billing.nim == "2025001-0105", Billing.semester == semester
                )
            ).first()
            if b_overdue and b_overdue.status != BillingStatus.PAID:
                b_overdue.due_date = today - timedelta(days=75)
                b_overdue.late_fee = calculate_late_fee(
                    b_overdue.amount,
                    b_overdue.due_date,
                    today,
                    b_overdue.status,
                    self.late_fee_config,
                )
                b_overdue.set_status(BillingStatus.OVERDUE)
                self.db.commit()

            return {
                "detail": "Data demo modul keuangan berhasil dimuat",
                "semester": semester,
                "newly_generated": gen.created_count,
            }
        except Exception:
            self.db.rollback()
            raise
