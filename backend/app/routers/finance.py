from __future__ import annotations

from datetime import date
import json
from typing import Any

from fastapi import APIRouter, Depends, Header, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db as get_orm_db
from app.core.security import require_admin_akademik
from app.models.finance import (
    FinanceError,
    PaymentMethod,
    seed_payment_methods,
)
from app.schemas.finance import (
    AIFinancialReportResponse,
    BillingItemResponse,
    CSVReportRequest,
    FinanceDashboardResponse,
    GenerateBillingRequest,
    GenerateBillingResponse,
    ManualPaymentRequest,
    PaymentActionResponse,
    PaymentMethodResponse,
    RefreshOverdueRequest,
    RefreshOverdueResponse,
    SchedulerStatusResponse,
    StudentFinanceSummaryItem,
    WebhookAckResponse,
    WebhookSignRequest,
    WebhookSignResponse,
)
from app.services.billing_service import (
    BillingService,
    finance_notification_history,
)
from app.services.finance_ai_report import (
    generate_financial_insights,
    generate_financial_insights_from_csv,
)
from app.services.finance_calculator import (
    compute_webhook_signature,
    quantize_money,
    to_decimal,
)
from app.services.finance_scheduler import default_finance_scheduler

router = APIRouter()
ADMIN_DEPS = [Depends(require_admin_akademik)]


def get_billing_service(db: Session = Depends(get_orm_db)) -> BillingService:
    """Menginjeksikan BillingService dengan SQLAlchemy Session."""
    return BillingService(db=db)


# ------------------------------------------------------------------
# Endpoint statis didaftarkan SEBELUM route berparameter dinamis
# ------------------------------------------------------------------


@router.get(
    "/payment-methods",
    response_model=list[PaymentMethodResponse],
    status_code=status.HTTP_200_OK,
)
def list_payment_methods(
    db: Session = Depends(get_orm_db),
) -> list[PaymentMethodResponse]:
    """Mengembalikan daftar metode pembayaran aktif (Virtual Account, QRIS, Transfer, Loket)."""
    methods = list(
        db.scalars(
            select(PaymentMethod)
            .where(PaymentMethod.is_active.is_(True))
            .order_by(PaymentMethod.id.asc())
        ).all()
    )
    if not methods:
        methods = seed_payment_methods(db)
        db.commit()
    return [PaymentMethodResponse.model_validate(m) for m in methods]


@router.post(
    "/billings/generate",
    response_model=GenerateBillingResponse,
    status_code=status.HTTP_200_OK,
    dependencies=ADMIN_DEPS,
)
def generate_semester_billings(
    body: GenerateBillingRequest,
    service: BillingService = Depends(get_billing_service),
) -> GenerateBillingResponse:
    """Membuat tagihan SPP semester untuk seluruh mahasiswa aktif (Admin Akademik)."""
    res = service.generate_billing(
        semester=body.semester,
        semester_start=body.semester_start,
    )
    items = [
        BillingItemResponse(**row)
        for row in service.list_billings(semester=res.semester)
    ]
    return GenerateBillingResponse(
        semester=res.semester,
        semester_start=res.semester_start,
        due_date=res.due_date,
        created_count=res.created_count,
        skipped_count=res.skipped_count,
        billings=items,
    )


@router.post(
    "/billings/refresh-overdue",
    response_model=RefreshOverdueResponse,
    status_code=status.HTTP_200_OK,
    dependencies=ADMIN_DEPS,
)
def refresh_overdue_and_reminders(
    body: RefreshOverdueRequest | None = None,
    service: BillingService = Depends(get_billing_service),
) -> RefreshOverdueResponse:
    """Menghitung denda keterlambatan, status overdue, dan mengirim reminder otomatis."""
    req = body or RefreshOverdueRequest()
    res = service.refresh_overdue_and_send_reminders(
        as_of=req.as_of,
        reminder_before_days=req.reminder_before_days,
    )
    return RefreshOverdueResponse(
        as_of=res.as_of,
        overdue_updated=res.overdue_updated,
        late_fees_applied=res.late_fees_applied,
        reminders_sent=res.reminders_sent,
    )


@router.get(
    "/billings",
    response_model=list[BillingItemResponse],
    status_code=status.HTTP_200_OK,
    dependencies=ADMIN_DEPS,
)
def list_billings(
    nim: str | None = Query(default=None),
    semester: str | None = Query(default=None),
    billing_status: str | None = Query(default=None, alias="status"),
    service: BillingService = Depends(get_billing_service),
) -> list[BillingItemResponse]:
    """Mengembalikan daftar tagihan SPP beserta filter opsional."""
    rows = service.list_billings(
        nim=nim, semester=semester, status_filter=billing_status
    )
    return [BillingItemResponse(**row) for row in rows]


@router.post(
    "/payments",
    response_model=PaymentActionResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=ADMIN_DEPS,
)
def record_manual_payment(
    body: ManualPaymentRequest,
    service: BillingService = Depends(get_billing_service),
) -> PaymentActionResponse:
    """Mencatat pembayaran SPP manual (cicilan atau pelunasan) secara atomik."""
    res = service.process_payment(
        billing_id=body.billing_id,
        amount=body.amount,
        method_code=body.method_code,
        transaction_id=body.transaction_id,
        source="manual",
        notes=body.notes,
    )
    detail = (
        f"Pembayaran duplikat diabaikan secara idempoten (tx={res.payment.transaction_id})"
        if res.idempotent_replay
        else f"Pembayaran berhasil dicatat; status tagihan {res.new_status.value}"
    )
    return PaymentActionResponse(
        billing_id=res.billing.id,
        invoice_number=res.billing.invoice_number,
        transaction_id=res.payment.transaction_id,
        amount=f"{quantize_money(to_decimal(res.payment.amount)):.2f}",
        method_code=body.method_code.strip().upper(),
        previous_status=res.previous_status.value,
        new_status=res.new_status.value,
        amount_paid=f"{quantize_money(to_decimal(res.billing.amount_paid)):.2f}",
        remaining=f"{res.billing.remaining:.2f}",
        overpayment=f"{res.overpayment:.2f}",
        idempotent_replay=res.idempotent_replay,
        detail=detail,
    )


@router.post(
    "/webhook/sign",
    response_model=WebhookSignResponse,
    status_code=status.HTTP_200_OK,
    dependencies=ADMIN_DEPS,
)
def sign_webhook_payload_helper(body: WebhookSignRequest) -> WebhookSignResponse:
    """Helper simulasi admin untuk menghasilkan signature HMAC-SHA256 & contoh curl."""
    payload: dict[str, Any] = {
        "transaction_id": body.transaction_id,
        "amount": f"{quantize_money(body.amount):.2f}",
        "status": body.status,
        "payment_method": body.payment_method,
    }
    if body.billing_id is not None:
        payload["billing_id"] = body.billing_id
    if body.invoice_number is not None:
        payload["invoice_number"] = body.invoice_number

    payload_json = json.dumps(payload, separators=(",", ":"))
    signature = compute_webhook_signature(
        payload_json.encode("utf-8"), settings.PAYMENT_WEBHOOK_SECRET
    )
    curl_cmd = (
        "curl -X POST http://127.0.0.1:8000/api/finance/webhook "
        '-H "Content-Type: application/json" '
        f'-H "X-Webhook-Signature: {signature}" '
        f"-d '{payload_json}'"
    )
    return WebhookSignResponse(
        payload_json=payload_json,
        signature=signature,
        curl_command=curl_cmd,
    )


@router.post(
    "/webhook",
    response_model=WebhookAckResponse,
    status_code=status.HTTP_200_OK,
)
async def receive_payment_webhook(
    request: Request,
    x_webhook_signature: str | None = Header(
        default=None, alias="X-Webhook-Signature"
    ),
    service: BillingService = Depends(get_billing_service),
) -> WebhookAckResponse:
    """Endpoint webhook payment gateway: verifikasi HMAC-SHA256, update billing atomik, & kirim receipt."""
    raw_body = await request.body()
    try:
        parsed = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FinanceError(
            "Payload webhook harus berupa objek JSON yang valid", status_code=422
        ) from exc

    if not isinstance(parsed, dict):
        raise FinanceError("Payload webhook harus berupa objek JSON", status_code=422)

    res = service.handle_webhook(
        raw_body=raw_body,
        signature=x_webhook_signature,
        payload=parsed,
    )
    return WebhookAckResponse(
        ok=True,
        transaction_id=res.transaction_id,
        billing_id=res.billing_id,
        invoice_number=res.invoice_number,
        gateway_status=res.gateway_status,
        billing_status=res.billing_status.value,
        processed_payment=res.processed_payment,
        idempotent_replay=res.idempotent_replay,
        message=res.message,
    )


@router.get(
    "/dashboard",
    response_model=FinanceDashboardResponse,
    status_code=status.HTTP_200_OK,
    dependencies=ADMIN_DEPS,
)
def get_finance_dashboard(
    semester: str | None = Query(default=None),
    service: BillingService = Depends(get_billing_service),
) -> FinanceDashboardResponse:
    """Mengembalikan ringkasan real-time per mahasiswa, collection rate prodi, & grafik bulanan."""
    data = service.get_dashboard_overview(semester=semester)
    return FinanceDashboardResponse(**data)


@router.get(
    "/students/{nim}/summary",
    response_model=StudentFinanceSummaryItem,
    status_code=status.HTTP_200_OK,
)
def get_student_finance_summary(
    nim: str,
    semester: str | None = Query(default=None),
    service: BillingService = Depends(get_billing_service),
) -> StudentFinanceSummaryItem:
    """Ringkasan kewajiban SPP & status blokir KRS seorang mahasiswa."""
    rows = service.get_student_summary(nim=nim, semester=semester)
    if not rows:
        return StudentFinanceSummaryItem(
            nim=nim,
            nama_mahasiswa=nim,
            program_studi="-",
            total_tagihan="0.00",
            sudah_bayar="0.00",
            sisa="0.00",
            status="no_billing",
            krs_blocked=False,
        )
    return StudentFinanceSummaryItem(**rows[0])


@router.get(
    "/receipts",
    status_code=status.HTTP_200_OK,
    dependencies=ADMIN_DEPS,
)
def list_finance_receipt_logs() -> list[dict[str, Any]]:
    """Mengembalikan daftar log simulasi pengiriman email kwitansi & reminder SPP."""
    return [rec.to_dict() for rec in reversed(finance_notification_history)]


@router.get(
    "/scheduler/jobs",
    response_model=SchedulerStatusResponse,
    status_code=status.HTTP_200_OK,
    dependencies=ADMIN_DEPS,
)
def get_scheduler_jobs() -> SchedulerStatusResponse:
    """Mengembalikan status APScheduler dan daftar cron job keuangan."""
    return SchedulerStatusResponse(
        running=default_finance_scheduler.is_running,
        jobs=default_finance_scheduler.get_jobs_status(),
    )


@router.get(
    "/ai-report",
    response_model=AIFinancialReportResponse,
    status_code=status.HTTP_200_OK,
    dependencies=ADMIN_DEPS,
)
def get_ai_financial_report(
    semester: str | None = Query(default=None),
    as_of: date | None = Query(default=None),
    service: BillingService = Depends(get_billing_service),
) -> AIFinancialReportResponse:
    """Menghasilkan AI Financial Insights (JSON) langsung dari data pembayaran & tunggakan DB."""
    rows = service.export_payment_csv_rows(semester=semester)
    report = generate_financial_insights(rows, as_of=as_of)
    return AIFinancialReportResponse(**report)


@router.post(
    "/ai-report/csv",
    response_model=AIFinancialReportResponse,
    status_code=status.HTTP_200_OK,
    dependencies=ADMIN_DEPS,
)
def analyze_csv_financial_report(
    body: CSVReportRequest,
) -> AIFinancialReportResponse:
    """Menganalisis CSV `nim, jumlah, tanggal, status` menjadi JSON AI Financial Insights."""
    report = generate_financial_insights_from_csv(
        body.csv_data,
        as_of=body.as_of,
    )
    return AIFinancialReportResponse(**report)


@router.post(
    "/seed-demo",
    status_code=status.HTTP_200_OK,
    dependencies=ADMIN_DEPS,
)
def seed_finance_demo(
    semester: str = Query(default="20251"),
    service: BillingService = Depends(get_billing_service),
) -> dict[str, Any]:
    """Memuat skenario data demo Modul Keuangan (Teknik 5jt, Ekonomi 4jt, cicilan, & overdue)."""
    return service.seed_demo_data(semester=semester)
