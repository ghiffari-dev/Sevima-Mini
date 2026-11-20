from __future__ import annotations

from datetime import date
import json
import logging
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.services.finance_calculator import (
    FinancialAnalyticsSummary,
    PaymentCSVRow,
    analyze_payment_records,
    format_rupiah,
    parse_payment_csv,
)
from app.services.schedule_recommender import LLMClient, get_default_llm_client

logger = logging.getLogger("finance.ai_report")


class AINarrativeOutput(BaseModel):
    """Skema validasi output narasi dari LLM agar aman dari halusinasi format."""

    ringkasan_eksekutif: str = Field(..., min_length=5, max_length=600)
    saran_tindak_lanjut: list[str] = Field(..., min_length=1, max_length=5)


def _extract_json_object(raw_text: str) -> dict[str, Any] | None:
    """Mengekstrak objek JSON pertama dari teks keluaran LLM (mendukung markdown fence)."""
    if not raw_text:
        return None
    text = raw_text.strip()
    start_obj = text.find("{")
    end_obj = text.rfind("}")
    if start_obj == -1 or end_obj == -1 or end_obj <= start_obj:
        return None
    candidate = text[start_obj : end_obj + 1]
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, dict):
        return parsed
    return None


def _build_deterministic_narrative(
    summary: FinancialAnalyticsSummary,
) -> AINarrativeOutput:
    """Menyusun narasi & saran tindak lanjut deterministik ketika LLM tidak aktif/gagal."""
    rev_str = format_rupiah(summary.total_revenue_bulan_ini)
    rate_str = f"{summary.collection_rate_percent:.2f}"
    z_count = summary.mahasiswa_tunggakan_lebih_2_bulan

    ringkasan = (
        f"Total pendapatan SPP bulan berjalan mencapai {rev_str} dengan collection rate "
        f"{rate_str}% ({summary.mahasiswa_lunas} dari {summary.total_mahasiswa} mahasiswa lunas). "
        f"Terdapat {z_count} mahasiswa dengan tunggakan lebih dari 2 bulan."
    )
    saran = [
        summary.rekomendasi,
        "Pertahankan pemblokiran akses pengisian KRS bagi mahasiswa berstatus unpaid, partial, atau overdue.",
        "Pantau pembayaran cicilan mahasiswa di daftar 10 tunggakan terbesar secara berkala.",
    ]
    return AINarrativeOutput(
        ringkasan_eksekutif=ringkasan,
        saran_tindak_lanjut=saran,
    )


def _build_anonymized_prompt(summary: FinancialAnalyticsSummary) -> str:
    """Membentuk prompt ringkas hanya dari agregasi numerik (tanpa PII mahasiswa)."""
    top_amounts = [
        f"Mahasiswa #{idx}: tunggakan {format_rupiah(item.total_tunggakan)} "
        f"({item.hari_tunggakan} hari, status {item.status})"
        for idx, item in enumerate(summary.top_10_tunggakan[:5], start=1)
    ]
    return (
        "Anda adalah analis keuangan universitas. Berikan ringkasan eksekutif singkat dan "
        "maksimal 3 saran tindak lanjut berdasarkan metrik agregat terverifikasi berikut "
        "(JANGAN mengubah angka): "
        f"As of: {summary.as_of.isoformat()}; "
        f"Total revenue bulan ini: {format_rupiah(summary.total_revenue_bulan_ini)}; "
        f"Collection rate: {summary.collection_rate_percent:.2f}% "
        f"({summary.mahasiswa_lunas}/{summary.total_mahasiswa} lunas); "
        f"Tunggakan >2 bulan: {summary.mahasiswa_tunggakan_lebih_2_bulan} mahasiswa; "
        f"Sampel 5 tunggakan tertinggi: {'; '.join(top_amounts) or 'tidak ada'}. "
        'Balas HANYA dalam JSON valid: {"ringkasan_eksekutif": "...", "saran_tindak_lanjut": ["...", "..."]}.'
    )


def generate_financial_insights(
    rows: list[PaymentCSVRow],
    *,
    as_of: date | None = None,
    llm_client: LLMClient | None = None,
) -> dict[str, Any]:
    """Menghasilkan JSON laporan keuangan lengkap dengan angka deterministik + narasi AI."""
    summary = analyze_payment_records(rows, as_of=as_of)

    client = llm_client if llm_client is not None else get_default_llm_client()
    ai_source = "deterministic_fallback"
    narrative: AINarrativeOutput | None = None

    if client is not None:
        try:
            raw_resp = client.complete(_build_anonymized_prompt(summary))
            extracted = _extract_json_object(raw_resp)
            if extracted is not None:
                narrative = AINarrativeOutput.model_validate(extracted)
                ai_source = "llm"
        except (ValidationError, Exception) as exc:
            logger.warning("LLM financial report fallback aktif: %s", exc)
            narrative = None

    if narrative is None:
        narrative = _build_deterministic_narrative(summary)

    rev_formatted = format_rupiah(summary.total_revenue_bulan_ini)
    return {
        "as_of": summary.as_of.isoformat(),
        "ai_source": ai_source,
        "total_revenue_bulan_ini": f"{summary.total_revenue_bulan_ini:.2f}",
        "total_revenue_bulan_ini_formatted": rev_formatted,
        "collection_rate_percent": f"{summary.collection_rate_percent:.2f}",
        "collection_rate_summary": (
            f"{summary.collection_rate_percent:.2f}% mahasiswa sudah bayar"
        ),
        "total_mahasiswa": summary.total_mahasiswa,
        "mahasiswa_lunas": summary.mahasiswa_lunas,
        "top_10_tunggakan": [
            {
                "nim": item.nim,
                "total_tunggakan": f"{item.total_tunggakan:.2f}",
                "total_tunggakan_formatted": format_rupiah(item.total_tunggakan),
                "hari_tunggakan": item.hari_tunggakan,
                "status": item.status,
            }
            for item in summary.top_10_tunggakan
        ],
        "mahasiswa_tunggakan_lebih_2_bulan": summary.mahasiswa_tunggakan_lebih_2_bulan,
        "rekomendasi": summary.rekomendasi,
        "ringkasan_eksekutif": narrative.ringkasan_eksekutif,
        "saran_tindak_lanjut": narrative.saran_tindak_lanjut,
    }


def generate_financial_insights_from_csv(
    csv_text: str,
    *,
    as_of: date | None = None,
    llm_client: LLMClient | None = None,
) -> dict[str, Any]:
    """Mem-parsing CSV `nim, jumlah, tanggal, status` lalu menghasilkan JSON AI Financial Insights."""
    rows = parse_payment_csv(csv_text)
    return generate_financial_insights(rows, as_of=as_of, llm_client=llm_client)
