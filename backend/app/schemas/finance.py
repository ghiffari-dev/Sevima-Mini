from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, Field


class PaymentMethodResponse(BaseModel):
    """Skema respons master metode pembayaran SPP."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    provider: str
    is_active: bool


class GenerateBillingRequest(BaseModel):
    """Payload permintaan generate tagihan SPP massal per semester."""

    semester: str = Field(..., min_length=3, max_length=10, examples=["20251"])
    semester_start: date | None = None


class BillingItemResponse(BaseModel):
    """Skema detail satu tagihan SPP mahasiswa."""

    id: int
    invoice_number: str
    nim: str
    nama_mahasiswa: str
    semester: str
    program_studi_id: int
    program_studi_nama: str
    amount: str
    late_fee: str
    total_tagihan: str
    sudah_bayar: str
    sisa: str
    due_date: date
    status: str
    krs_blocked: bool
    paid_at: datetime | None = None


class GenerateBillingResponse(BaseModel):
    """Hasil eksekusi generate_billing per semester."""

    semester: str
    semester_start: date
    due_date: date
    created_count: int
    skipped_count: int
    billings: list[BillingItemResponse]


class ManualPaymentRequest(BaseModel):
    """Payload pencatatan pembayaran SPP manual oleh admin/loket keuangan."""

    billing_id: int = Field(..., ge=1)
    amount: Decimal = Field(..., gt=0)
    method_code: str = Field(..., min_length=2, max_length=40, examples=["MANUAL_CASH"])
    transaction_id: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=300)


class PaymentActionResponse(BaseModel):
    """Skema respons hasil pemrosesan pembayaran SPP."""

    billing_id: int
    invoice_number: str
    transaction_id: str
    amount: str
    method_code: str
    previous_status: str
    new_status: str
    amount_paid: str
    remaining: str
    overpayment: str
    idempotent_replay: bool
    detail: str


class WebhookSignRequest(BaseModel):
    """Payload bantu untuk menghasilkan signature HMAC-SHA256 & contoh perintah curl."""

    billing_id: int | None = None
    invoice_number: str | None = None
    transaction_id: str = Field(..., min_length=3, max_length=100)
    amount: Decimal = Field(..., gt=0)
    status: str = Field(default="paid")
    payment_method: str = Field(default="VA_BCA")


class WebhookSignResponse(BaseModel):
    """Hasil signing payload webhook simulasi gateway."""

    payload_json: str
    signature: str
    curl_command: str


class WebhookAckResponse(BaseModel):
    """Respons 200 OK dari endpoint webhook payment gateway."""

    ok: bool = True
    transaction_id: str
    billing_id: int
    invoice_number: str
    gateway_status: str
    billing_status: str
    processed_payment: bool
    idempotent_replay: bool
    message: str


class RefreshOverdueRequest(BaseModel):
    """Parameter manual job pengecekan overdue, denda, dan pengingat SPP."""

    as_of: date | None = None
    reminder_before_days: int = Field(default=3, ge=0, le=30)


class RefreshOverdueResponse(BaseModel):
    """Hasil eksekusi job overdue & pengingat SPP."""

    as_of: date
    overdue_updated: int
    late_fees_applied: int
    reminders_sent: int


class StudentFinanceSummaryItem(BaseModel):
    """Ringkasan kewajiban dan status blokir KRS per mahasiswa."""

    nim: str
    nama_mahasiswa: str
    program_studi: str
    total_tagihan: str
    sudah_bayar: str
    sisa: str
    status: str
    krs_blocked: bool
    latest_billing_id: int | None = None
    latest_invoice_number: str | None = None
    latest_due_date: date | None = None


class ProdiCollectionRateItem(BaseModel):
    """Collection rate dan total tagihan per program studi."""

    program_studi_id: int
    kode_prodi: str
    nama_prodi: str
    fakultas: str
    total_tagihan_count: int
    lunas_count: int
    collection_rate: str
    total_billed: str
    total_collected: str
    total_outstanding: str


class MonthlyPaymentItem(BaseModel):
    """Agregasi pembayaran SPP per bulan untuk grafik dashboard."""

    month: str
    total_amount: str
    transaction_count: int


class FinanceDashboardResponse(BaseModel):
    """Skema lengkap data real-time Dashboard Keuangan."""

    semester: str
    total_mahasiswa: int
    mahasiswa_lunas: int
    mahasiswa_menunggak: int
    overall_collection_rate: str
    total_tagihan: str
    total_terbayar: str
    total_tunggakan: str
    students: list[StudentFinanceSummaryItem]
    per_prodi: list[ProdiCollectionRateItem]
    monthly_payments: list[MonthlyPaymentItem]


class CSVReportRequest(BaseModel):
    """Payload input CSV `nim, jumlah, tanggal, status` untuk analisis laporan AI."""

    csv_data: str = Field(..., min_length=1)
    as_of: date | None = None


class ArrearsItemResponse(BaseModel):
    """Item mahasiswa dalam daftar Top 10 Tunggakan Terbesar."""

    nim: str
    total_tunggakan: str
    total_tunggakan_formatted: str
    hari_tunggakan: int
    status: str


class AIFinancialReportResponse(BaseModel):
    """Output JSON AI Financial Insights untuk dashboard frontend."""

    as_of: str
    ai_source: str
    total_revenue_bulan_ini: str
    total_revenue_bulan_ini_formatted: str
    collection_rate_percent: str
    collection_rate_summary: str
    total_mahasiswa: int
    mahasiswa_lunas: int
    top_10_tunggakan: list[ArrearsItemResponse]
    mahasiswa_tunggakan_lebih_2_bulan: int
    rekomendasi: str
    ringkasan_eksekutif: str
    saran_tindak_lanjut: list[str]


class SchedulerJobItem(BaseModel):
    """Informasi satu job APScheduler."""

    id: str
    name: str
    trigger: str
    next_run_time: str | None = None


class SchedulerStatusResponse(BaseModel):
    """Status background scheduler dan daftar cron job."""

    running: bool
    jobs: list[SchedulerJobItem]
