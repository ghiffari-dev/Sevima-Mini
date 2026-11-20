from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import hmac
import io

from app.core.config import settings
from app.models.finance import BillingStatus, FinanceError

CENT = Decimal("0.01")
ZERO = Decimal("0.00")
PAID_STATUS_ALIASES = frozenset({"paid", "lunas", "success", "settlement"})
IGNORED_NON_DEBT_STATUSES = frozenset({"cancelled", "refunded", "void"})


@dataclass(frozen=True)
class LateFeeConfig:
    """Konfigurasi perhitungan denda keterlambatan SPP berbasis Decimal."""

    rate_per_month: Decimal = Decimal("0.02")
    max_rate: Decimal = Decimal("0.10")
    grace_days: int = 0
    days_per_month: int = 30

    @classmethod
    def from_settings(cls) -> "LateFeeConfig":
        """Membaca konfigurasi default denda keterlambatan dari Settings."""
        return cls(
            rate_per_month=Decimal(str(settings.LATE_FEE_RATE_PER_MONTH)),
            max_rate=Decimal(str(settings.LATE_FEE_MAX_RATE)),
            grace_days=int(settings.LATE_FEE_GRACE_DAYS),
            days_per_month=30,
        )


def to_decimal(value: Decimal | int | str) -> Decimal:
    """Mengonversi angka/string ke Decimal tanpa melalui float."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(str(value))
    return Decimal(value)


def quantize_money(value: Decimal) -> Decimal:
    """Membulatkan nilai uang ke 2 angka di belakang koma (ROUND_HALF_UP)."""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def calculate_late_fee(
    base_amount: Decimal | int | str,
    due_date: date,
    as_of: date,
    status: BillingStatus | str,
    config: LateFeeConfig | None = None,
) -> Decimal:
    """Menghitung denda keterlambatan SPP secara deterministik dengan batas maksimal.

    - Tagihan `paid` atau belum melewati jatuh tempo (+ grace_days) mendapat denda `0.00`.
    - Keterlambatan dihitung per blok 30 hari (ceiling) dengan tarif default 2%/bulan
      dan batas maksimal 10% dari pokok tagihan.
    """
    cfg = config or LateFeeConfig.from_settings()
    base = to_decimal(base_amount)
    status_enum = status if isinstance(status, BillingStatus) else BillingStatus(str(status).lower())

    if status_enum == BillingStatus.PAID or base <= ZERO or as_of <= due_date:
        return ZERO

    overdue_days = (as_of - due_date).days
    effective_days = overdue_days - cfg.grace_days
    if effective_days <= 0:
        return ZERO

    months_late = (effective_days + cfg.days_per_month - 1) // cfg.days_per_month
    effective_rate = min(cfg.rate_per_month * months_late, cfg.max_rate)
    return quantize_money(base * effective_rate)


def determine_billing_status(
    total_due: Decimal | int | str,
    total_paid: Decimal | int | str,
    due_date: date,
    as_of: date,
) -> BillingStatus:
    """Menentukan status billing berdasarkan total kewajiban, pembayaran kumulatif, dan jatuh tempo."""
    due = quantize_money(to_decimal(total_due))
    paid = quantize_money(to_decimal(total_paid))

    if paid >= due:
        return BillingStatus.PAID
    if as_of > due_date:
        return BillingStatus.OVERDUE
    if paid > ZERO:
        return BillingStatus.PARTIAL
    return BillingStatus.UNPAID


def resolve_spp_amount(
    prodi_nama: str,
    fakultas: str,
    explicit_biaya: Decimal | int | str | None = None,
    *,
    teknik_amount: Decimal | int | str | None = None,
    ekonomi_amount: Decimal | int | str | None = None,
    default_amount: Decimal | int | str | None = None,
) -> Decimal:
    """Menentukan tarif SPP per semester dari biaya_spp prodi atau aturan fakultas/prodi."""
    if explicit_biaya is not None:
        explicit_dec = quantize_money(to_decimal(explicit_biaya))
        if explicit_dec > ZERO:
            return explicit_dec

    teknik = quantize_money(
        to_decimal(teknik_amount if teknik_amount is not None else settings.SPP_TEKNIK_AMOUNT)
    )
    ekonomi = quantize_money(
        to_decimal(ekonomi_amount if ekonomi_amount is not None else settings.SPP_EKONOMI_AMOUNT)
    )
    default = quantize_money(
        to_decimal(default_amount if default_amount is not None else settings.SPP_DEFAULT_AMOUNT)
    )

    combined = f"{prodi_nama} {fakultas}".lower()
    if "teknik" in combined:
        return teknik
    if "ekonomi" in combined:
        return ekonomi
    return default


def compute_percentage(
    numerator: int | Decimal, denominator: int | Decimal
) -> Decimal:
    """Menghitung persentase 0.00..100.00 aman pembagian nol dengan ROUND_HALF_UP."""
    num = Decimal(str(numerator))
    den = Decimal(str(denominator))
    if den <= ZERO:
        return ZERO
    return quantize_money((num * Decimal("100")) / den)


def format_rupiah(amount: Decimal | int | str) -> str:
    """Memformat nominal Decimal menjadi string Rupiah mudah baca (mis. Rp 5.000.000)."""
    val = quantize_money(to_decimal(amount))
    sign = "-" if val < ZERO else ""
    abs_val = abs(val)
    whole = int(abs_val)
    frac = abs_val - Decimal(whole)
    whole_str = f"{whole:,}".replace(",", ".")
    if frac > ZERO:
        cents = f"{frac:.2f}".split(".")[1]
        return f"{sign}Rp {whole_str},{cents}"
    return f"{sign}Rp {whole_str}"


def compute_webhook_signature(raw_body: bytes, secret: str) -> str:
    """Menghitung hex digest HMAC-SHA256 atas raw payload webhook."""
    return hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()


def verify_webhook_signature(
    raw_body: bytes, signature: str | None, secret: str
) -> bool:
    """Memverifikasi signature webhook HMAC-SHA256 secara constant-time."""
    if not signature or not secret:
        return False
    provided = signature.strip().lower()
    if provided.startswith("sha256="):
        provided = provided[len("sha256=") :]
    if not provided:
        return False
    expected = compute_webhook_signature(raw_body, secret).lower()
    return hmac.compare_digest(expected, provided)


@dataclass(frozen=True)
class PaymentCSVRow:
    """Baris data pembayaran/tagihan untuk analitik finansial deterministik."""

    nim: str
    jumlah: Decimal
    tanggal: date
    status: str
    sisa: Decimal | None = None
    due_date: date | None = None


@dataclass(frozen=True)
class ArrearsItem:
    """Ringkasan tunggakan per mahasiswa untuk Top 10 Tunggakan Terbesar."""

    nim: str
    total_tunggakan: Decimal
    hari_tunggakan: int
    status: str


@dataclass(frozen=True)
class FinancialAnalyticsSummary:
    """Hasil agregasi deterministik laporan keuangan untuk AI Financial Insights."""

    as_of: date
    total_revenue_bulan_ini: Decimal
    collection_rate_percent: Decimal
    total_mahasiswa: int
    mahasiswa_lunas: int
    top_10_tunggakan: tuple[ArrearsItem, ...]
    mahasiswa_tunggakan_lebih_2_bulan: int
    rekomendasi: str


def parse_payment_csv(csv_text: str) -> list[PaymentCSVRow]:
    """Mem-parsing CSV `nim, jumlah, tanggal, status` (dengan kolom opsional sisa/due_date)."""
    cleaned = csv_text.strip()
    if not cleaned:
        return []

    reader = csv.DictReader(io.StringIO(cleaned))
    if reader.fieldnames is None:
        raise FinanceError("Header CSV tidak ditemukan", status_code=422)

    normalized_fields = {f.strip().lower(): f for f in reader.fieldnames if f is not None}
    required = {"nim", "jumlah", "tanggal", "status"}
    missing = sorted(required - set(normalized_fields.keys()))
    if missing:
        raise FinanceError(
            f"Kolom wajib CSV tidak lengkap: {', '.join(missing)}",
            status_code=422,
        )

    rows: list[PaymentCSVRow] = []
    for idx, raw_row in enumerate(reader, start=2):
        row = {
            (k.strip().lower() if k else ""): (v.strip() if isinstance(v, str) else "")
            for k, v in raw_row.items()
        }
        nim = row.get("nim", "")
        if not nim:
            raise FinanceError(f"Baris CSV {idx}: kolom nim kosong", status_code=422)
        try:
            jumlah = quantize_money(Decimal(row["jumlah"]))
        except (InvalidOperation, ValueError) as exc:
            raise FinanceError(
                f"Baris CSV {idx}: nominal jumlah tidak valid ({row.get('jumlah')})",
                status_code=422,
            ) from exc
        if jumlah < ZERO:
            raise FinanceError(
                f"Baris CSV {idx}: nominal jumlah tidak boleh negatif",
                status_code=422,
            )
        try:
            tanggal = date.fromisoformat(row["tanggal"])
        except ValueError as exc:
            raise FinanceError(
                f"Baris CSV {idx}: format tanggal harus YYYY-MM-DD ({row.get('tanggal')})",
                status_code=422,
            ) from exc
        status_str = row.get("status", "").lower()
        if not status_str:
            raise FinanceError(f"Baris CSV {idx}: kolom status kosong", status_code=422)

        sisa_val: Decimal | None = None
        if row.get("sisa"):
            try:
                sisa_val = quantize_money(Decimal(row["sisa"]))
            except (InvalidOperation, ValueError) as exc:
                raise FinanceError(
                    f"Baris CSV {idx}: nominal sisa tidak valid ({row.get('sisa')})",
                    status_code=422,
                ) from exc

        due_date_val: date | None = None
        if row.get("due_date"):
            try:
                due_date_val = date.fromisoformat(row["due_date"])
            except ValueError as exc:
                raise FinanceError(
                    f"Baris CSV {idx}: format due_date harus YYYY-MM-DD ({row.get('due_date')})",
                    status_code=422,
                ) from exc

        rows.append(
            PaymentCSVRow(
                nim=nim,
                jumlah=jumlah,
                tanggal=tanggal,
                status=status_str,
                sisa=sisa_val,
                due_date=due_date_val,
            )
        )
    return rows


def analyze_payment_records(
    rows: list[PaymentCSVRow],
    as_of: date | None = None,
) -> FinancialAnalyticsSummary:
    """Menghitung metrik laporan keuangan (revenue, collection rate, top 10, tunggakan >2 bulan) secara murni."""
    ref_date = as_of or date.today()
    total_revenue = ZERO
    all_nims: set[str] = set()
    arrears_by_nim: dict[str, Decimal] = {}
    max_overdue_days_by_nim: dict[str, int] = {}
    status_by_nim: dict[str, str] = {}
    overdue_gt_2_months_nims: set[str] = set()

    for row in rows:
        status_norm = row.status.strip().lower()
        all_nims.add(row.nim)

        if status_norm in PAID_STATUS_ALIASES:
            if row.tanggal.year == ref_date.year and row.tanggal.month == ref_date.month:
                total_revenue += quantize_money(row.jumlah)
            continue

        if status_norm in IGNORED_NON_DEBT_STATUSES:
            continue

        unpaid_amount = quantize_money(row.sisa if row.sisa is not None else row.jumlah)
        if unpaid_amount <= ZERO:
            continue

        due_ref = row.due_date if row.due_date is not None else row.tanggal
        days_late = max(0, (ref_date - due_ref).days)

        arrears_by_nim[row.nim] = arrears_by_nim.get(row.nim, ZERO) + unpaid_amount
        prev_days = max_overdue_days_by_nim.get(row.nim, 0)
        if days_late >= prev_days:
            max_overdue_days_by_nim[row.nim] = days_late
            status_by_nim[row.nim] = status_norm
        if days_late > 60:
            overdue_gt_2_months_nims.add(row.nim)

    total_mahasiswa = len(all_nims)
    mahasiswa_lunas = total_mahasiswa - len(arrears_by_nim)
    collection_rate = compute_percentage(mahasiswa_lunas, total_mahasiswa)

    sorted_arrears = sorted(
        (
            ArrearsItem(
                nim=nim,
                total_tunggakan=quantize_money(total_amt),
                hari_tunggakan=max_overdue_days_by_nim.get(nim, 0),
                status=status_by_nim.get(nim, "unpaid"),
            )
            for nim, total_amt in arrears_by_nim.items()
        ),
        key=lambda item: (-item.total_tunggakan, -item.hari_tunggakan, item.nim),
    )

    z_count = len(overdue_gt_2_months_nims)
    return FinancialAnalyticsSummary(
        as_of=ref_date,
        total_revenue_bulan_ini=quantize_money(total_revenue),
        collection_rate_percent=collection_rate,
        total_mahasiswa=total_mahasiswa,
        mahasiswa_lunas=mahasiswa_lunas,
        top_10_tunggakan=tuple(sorted_arrears[:10]),
        mahasiswa_tunggakan_lebih_2_bulan=z_count,
        rekomendasi=f"Kirim reminder ke {z_count} mahasiswa dengan tunggakan >2 bulan",
    )
