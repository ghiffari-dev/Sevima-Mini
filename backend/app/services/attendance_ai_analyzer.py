"""AI Attendance Analyzer (Minggu 12 — Deliverable 4 & Step 3).

Mengikuti pola Functional Core + Guardrail AI (`finance_ai_report.py`):
1. Menghitung persentase kehadiran per mahasiswa secara deterministik (`Decimal` ROUND_HALF_UP).
2. Mengidentifikasi mahasiswa dengan presensi < 75% (warning) dan early warning risiko.
3. Mendeteksi pola:
   - Mahasiswa yang sering absen pada hari/waktu tertentu (mis. Senin pagi).
   - Kelas/slot jam dengan tingkat absen tinggi (mis. jam 07:00 absen rate >= 30%).
4. Menghasilkan rekomendasi & insight terstruktur JSON (`insights` + `actions`),
   dengan dukungan `LLMClient` teranonimasi + fallback deterministik.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal
import json
import logging
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.models.schedule import format_hari, normalize_hari
from app.services.attendance_rules import TWO_PLACES, attendance_percentage
from app.services.schedule_recommender import LLMClient, get_default_llm_client

logger = logging.getLogger("attendance.ai_analyzer")

MIN_ATTENDANCE_PERCENT = Decimal("75.00")
HIGH_SLOT_ABSENCE_THRESHOLD = Decimal("30.00")


class AIAttendanceLLMOutput(BaseModel):
    """Skema validasi keluaran LLM untuk insight & action presensi."""

    insights: list[str] = Field(..., min_length=1, max_length=10)
    actions: list[str] = Field(..., min_length=1, max_length=10)


def _extract_json_object(raw_text: str) -> dict[str, Any] | None:
    """Mengekstrak objek JSON pertama dari respons teks LLM."""
    if not raw_text:
        return None
    text = raw_text.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _normalize_status(raw_status: Any) -> str:
    """Menormalkan string status menjadi 'hadir', 'terlambat', atau 'alpha'."""
    val = str(raw_status or "").strip().lower()
    if val in {"hadir", "present", "h", "1", "true"}:
        return "hadir"
    if val in {"terlambat", "late", "telat", "t"}:
        return "terlambat"
    return "alpha"


def _normalize_day_name(raw_hari: Any) -> str:
    """Menormalkan kode hari (1..6) atau nama hari menjadi bahasa Indonesia."""
    if raw_hari is None or str(raw_hari).strip() == "":
        return "Tidak Diketahui"
    try:
        return format_hari(raw_hari)
    except Exception:
        return str(raw_hari).strip().capitalize()


def _time_of_day_label(jam_str: str | None) -> str:
    """Mengembalikan label waktu ('pagi', 'siang', 'sore') dari string jam 'HH:MM'."""
    if not jam_str:
        return ""
    text = str(jam_str).strip()
    try:
        hour = int(text.split(":")[0])
    except (ValueError, IndexError):
        return ""
    if hour < 11:
        return "pagi"
    if hour < 15:
        return "siang"
    return "sore"


def _fmt_rate(percent: Decimal) -> str:
    """Menampilkan persentase integer tanpa '.00' jika bulat (40.00 -> 40%), atau 2 desimal."""
    if percent == percent.to_integral_value():
        return f"{int(percent)}%"
    return f"{percent:.2f}%"


def _label_mahasiswa(name: str) -> str:
    clean = name.strip()
    if clean.lower().startswith("mahasiswa "):
        return clean
    return f"Mahasiswa {clean}"


def _label_kelas(kelas: str) -> str:
    clean = kelas.strip()
    if clean.lower().startswith("kelas "):
        return clean
    return f"Kelas {clean}"



def analyze_attendance_records(
    records: list[dict[str, Any]],
    *,
    min_percent: Decimal = MIN_ATTENDANCE_PERCENT,
    llm_client: LLMClient | None = None,
) -> dict[str, Any]:
    """Menganalisis array data presensi dan menghasilkan JSON terstruktur (insights + actions)."""
    # 1. Agregasi per mahasiswa
    by_student: dict[str, dict[str, Any]] = {}
    # (nim, hari_nama, waktu_label) -> [absent_count, total_count]
    student_day_counts: dict[tuple[str, str, str], list[int]] = defaultdict(
        lambda: [0, 0]
    )
    # (kelas_label, hari_nama, jam_label) -> [absent_count, total_count]
    slot_counts: dict[tuple[str, str, str], list[int]] = defaultdict(lambda: [0, 0])

    for raw in records:
        item = raw if isinstance(raw, dict) else raw.model_dump()
        nim = str(item.get("nim") or "").strip()
        if not nim:
            continue
        nama = str(item.get("nama") or nim).strip()
        kelas = str(
            item.get("kelas") or item.get("kode_mk") or "Kelas Umum"
        ).strip()
        hari_nama = _normalize_day_name(item.get("hari"))
        jam = str(item.get("jam") or "").strip() or "08:00"
        if len(jam) >= 5 and jam[2] == ":":
            jam = jam[:5]
        waktu_lbl = _time_of_day_label(jam)
        status = _normalize_status(item.get("status"))

        st_entry = by_student.setdefault(
            nim,
            {
                "nim": nim,
                "nama": nama,
                "total_pertemuan": 0,
                "hadir": 0,
                "terlambat": 0,
                "alpha": 0,
            },
        )
        if nama and st_entry["nama"] == nim and nama != nim:
            st_entry["nama"] = nama

        st_entry["total_pertemuan"] += 1
        is_present = status in {"hadir", "terlambat"}
        if status == "hadir":
            st_entry["hadir"] += 1
        elif status == "terlambat":
            st_entry["terlambat"] += 1
        else:
            st_entry["alpha"] += 1

        day_bucket = student_day_counts[(nim, hari_nama, waktu_lbl)]
        day_bucket[1] += 1
        if not is_present:
            day_bucket[0] += 1

        slot_bucket = slot_counts[(kelas, hari_nama, jam)]
        slot_bucket[1] += 1
        if not is_present:
            slot_bucket[0] += 1

    # Hitung persentase kehadiran per mahasiswa & identifikasi < 75%
    student_attendance: list[dict[str, Any]] = []
    warning_under_75: list[dict[str, Any]] = []

    for nim in sorted(by_student.keys()):
        st = by_student[nim]
        attended = st["hadir"] + st["terlambat"]
        total = st["total_pertemuan"]
        persen = attendance_percentage(attended, total)
        is_warning = persen < min_percent
        row_out = {
            "nim": nim,
            "nama": st["nama"],
            "total_pertemuan": total,
            "hadir": st["hadir"],
            "terlambat": st["terlambat"],
            "alpha": st["alpha"],
            "persentase_kehadiran": f"{persen:.2f}",
            "warning": is_warning,
        }
        student_attendance.append(row_out)
        if is_warning:
            warning_under_75.append(row_out)

    # 3. Deteksi pattern
    detected_patterns: list[dict[str, Any]] = []
    deterministic_insights: list[str] = []
    deterministic_actions: list[str] = []

    risk_count = len(warning_under_75)
    early_warning = (
        f"{risk_count} mahasiswa berisiko tidak memenuhi syarat presensi (< {min_percent:.0f}%)"
        if risk_count > 0
        else "Seluruh mahasiswa saat ini memenuhi ambang batas presensi minimal 75%"
    )
    deterministic_insights.append(early_warning)

    for w in warning_under_75:
        deterministic_insights.append(
            f"Mahasiswa {w['nama']} ({w['nim']}) memiliki presensi {w['persentase_kehadiran']}% "
            f"(alpha {w['alpha']} dari {w['total_pertemuan']} sesi, di bawah batas 75%)."
        )

    # Pattern A: Mahasiswa sering absent pada hari/jam tertentu
    for (nim, hari_nama, waktu_lbl), (absent_cnt, total_cnt) in sorted(
        student_day_counts.items()
    ):
        if hari_nama == "Tidak Diketahui" or absent_cnt == 0:
            continue
        st_name = by_student[nim]["nama"]
        total_alpha_student = by_student[nim]["alpha"]
        # Terdeteksi pola jika absen >= 2 kali di hari tsb, atau 100% absen pada hari tsb (min 1)
        if absent_cnt >= 2 or (
            absent_cnt >= 1 and total_cnt >= 2 and absent_cnt == total_cnt
        ) or (total_alpha_student >= 2 and absent_cnt == total_alpha_student):
            day_phrase = f"{hari_nama} {waktu_lbl}".strip()
            rate = (
                Decimal(absent_cnt) * Decimal(100) / Decimal(total_cnt)
            ).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
            mhs_lbl = _label_mahasiswa(st_name)
            detected_patterns.append(
                {
                    "type": "student_day_absence",
                    "nim": nim,
                    "nama": st_name,
                    "hari": hari_nama,
                    "waktu": waktu_lbl or None,
                    "absent_count": absent_cnt,
                    "total_sessions": total_cnt,
                    "absence_rate_percent": f"{rate:.2f}",
                    "description": f"{mhs_lbl} sering absent hari {hari_nama}",
                }
            )
            deterministic_insights.append(
                f"{mhs_lbl} ({nim}) sering absent hari {day_phrase} "
                f"({absent_cnt}/{total_cnt} pertemuan)."
            )
            deterministic_actions.append(
                f"{mhs_lbl} sering absent {day_phrase} -> hubungi untuk konseling"
            )

    # Pattern B: Hari/jam kelas dengan absen rate tinggi (>= 30%)
    for (kelas, hari_nama, jam), (absent_cnt, total_cnt) in sorted(
        slot_counts.items()
    ):
        if total_cnt == 0 or absent_cnt == 0:
            continue
        absen_rate = (
            Decimal(absent_cnt) * Decimal(100) / Decimal(total_cnt)
        ).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
        if absen_rate >= HIGH_SLOT_ABSENCE_THRESHOLD:
            rate_label = _fmt_rate(absen_rate)
            kls_lbl = _label_kelas(kelas)
            detected_patterns.append(
                {
                    "type": "high_absence_slot",
                    "kelas": kelas,
                    "hari": hari_nama,
                    "jam": jam,
                    "absent_count": absent_cnt,
                    "total_records": total_cnt,
                    "absence_rate_percent": f"{absen_rate:.2f}",
                    "description": (
                        f"{kls_lbl} ({hari_nama} {jam}) memiliki absen rate {rate_label}"
                    ),
                }
            )
            deterministic_insights.append(
                f"Slot kuliah {kls_lbl} pada hari {hari_nama} jam {jam} memiliki tingkat ketidakhadiran tinggi ({rate_label})."
            )
            deterministic_actions.append(
                f"{kls_lbl} di jam {jam} absen rate {rate_label} -> pertimbangkan reschedule"
            )

    if not deterministic_actions:
        if warning_under_75:
            for w in warning_under_75:
                deterministic_actions.append(
                    f"Mahasiswa {w['nama']} ({w['nim']}) presensi {w['persentase_kehadiran']}% (<75%) -> hubungi untuk konseling akademik"
                )
        else:
            deterministic_actions.append(
                "Pertahankan jadwal dan kirim apresiasi kehadiran kepada mahasiswa"
            )

    # 4. Opsional: pengayaan narasi via LLMClient dengan prompt teranonimasi
    client = llm_client if llm_client is not None else get_default_llm_client()
    ai_source = "deterministic_fallback"
    final_insights = list(deterministic_insights)
    final_actions = list(deterministic_actions)

    if client is not None:
        try:
            anon_prompt = (
                "Anda adalah analis akademik universitas. Berdasarkan metrik presensi "
                f"terverifikasi berikut (total mahasiswa={len(student_attendance)}, "
                f"berisiko <75%={risk_count}, jumlah pola={len(detected_patterns)}), "
                'kembalikan JSON valid: {"insights": ["..."], "actions": ["..."]}.'
            )
            raw_resp = client.complete(anon_prompt)
            extracted = _extract_json_object(raw_resp)
            if extracted is not None:
                validated = AIAttendanceLLMOutput.model_validate(extracted)
                ai_source = "llm"
                # Gabungkan insight/action deterministik utama + tambahan LLM tanpa kehilangan angka pasti
                for item in validated.insights:
                    if item not in final_insights:
                        final_insights.append(item)
                for act in validated.actions:
                    if act not in final_actions:
                        final_actions.append(act)
        except (ValidationError, Exception) as exc:
            logger.warning("LLM attendance analyzer fallback aktif: %s", exc)

    return {
        "ai_source": ai_source,
        "early_warning": early_warning,
        "total_mahasiswa": len(student_attendance),
        "jumlah_mahasiswa_berisiko": risk_count,
        "student_attendance": student_attendance,
        "warning_under_75": warning_under_75,
        "detected_patterns": detected_patterns,
        "insights": final_insights,
        "actions": final_actions,
        "recommendations": final_actions,
    }
