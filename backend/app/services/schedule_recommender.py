from __future__ import annotations

from dataclasses import dataclass
from datetime import time
import json
import logging
import re
from typing import Any
import zlib

import httpx

from app.core.config import settings
from app.models.schedule import HARI_MAP, Jadwal, Ruangan, normalize_hari
from app.services.conflict_detector import (
    JadwalSlot,
    detect_conflicts_sweep,
    parse_time_value,
    to_minutes,
)

logger = logging.getLogger(__name__)

_DEFAULT_START_MINUTES = [
    8 * 60,   # 08:00 (prioritas pagi)
    10 * 60,  # 10:00 (prioritas pagi)
    13 * 60,  # 13:00 (prioritas siang)
    7 * 60,   # 07:00 (pagi awal)
    15 * 60,  # 15:00 (sore)
]


def _fmt_minutes(total_minutes: int) -> str:
    return f"{total_minutes // 60:02d}:{total_minutes % 60:02d}"


def _minutes_to_time(total_minutes: int) -> time:
    return time(total_minutes // 60, total_minutes % 60)


def _resolve_dosen_id(item: dict[str, Any], fallback_idx: int) -> int:
    if item.get("dosen_id") is not None:
        return int(item["dosen_id"])
    dosen_name = str(item.get("dosen") or "").strip().lower()
    if dosen_name:
        return int(zlib.crc32(dosen_name.encode("utf-8")) + 1)
    return -fallback_idx


@dataclass
class _ScheduleView:
    """Representasi internal seragam jadwal untuk AI rescheduler & fallback scorer."""

    id: int
    kode_mk: str
    nama_mk: str
    hari: int
    jam_mulai: time
    jam_selesai: time
    ruangan: str
    dosen_id: int
    dosen_nama: str
    enrolled_count: int
    kapasitas: int | None = None

    def to_slot(self, override_id: int | None = None) -> JadwalSlot:
        return JadwalSlot(
            id=self.id if override_id is None else override_id,
            hari=self.hari,
            jam_mulai=self.jam_mulai,
            jam_selesai=self.jam_selesai,
            ruangan_kode=self.ruangan.strip(),
            dosen_id=self.dosen_id,
        )


def _to_schedule_view(
    item: Jadwal | JadwalSlot | _ScheduleView | dict[str, Any],
    fallback_idx: int = 1,
) -> _ScheduleView:
    if isinstance(item, _ScheduleView):
        return item

    if isinstance(item, Jadwal):
        kelas = item.kelas
        mk = kelas.matakuliah if kelas else None
        return _ScheduleView(
            id=item.id,
            kode_mk=kelas.kode_mk if kelas else "",
            nama_mk=mk.nama if mk else (kelas.kode_mk if kelas else ""),
            hari=item.hari,
            jam_mulai=item.jam_mulai,
            jam_selesai=item.jam_selesai,
            ruangan=item.ruangan_kode,
            dosen_id=item.dosen_id,
            dosen_nama=item.dosen.nama if item.dosen else str(item.dosen_id),
            enrolled_count=kelas.kuota if kelas else 0,
            kapasitas=item.ruangan.kapasitas if item.ruangan else None,
        )

    if isinstance(item, JadwalSlot):
        return _ScheduleView(
            id=item.id,
            kode_mk="",
            nama_mk="",
            hari=item.hari,
            jam_mulai=item.jam_mulai,
            jam_selesai=item.jam_selesai,
            ruangan=item.ruangan_kode,
            dosen_id=item.dosen_id,
            dosen_nama=str(item.dosen_id),
            enrolled_count=0,
        )

    if isinstance(item, dict):
        jam_mulai_raw = item.get("jam_mulai")
        jam_selesai_raw = item.get("jam_selesai")
        if (jam_mulai_raw is None or jam_selesai_raw is None) and item.get("jam"):
            jam_str = str(item["jam"])
            if "-" in jam_str:
                jam_mulai_raw, jam_selesai_raw = jam_str.split("-", 1)
        if jam_mulai_raw is None or jam_selesai_raw is None:
            raise ValueError("Jadwal harus memiliki jam_mulai dan jam_selesai")

        mulai = parse_time_value(jam_mulai_raw)
        selesai = parse_time_value(jam_selesai_raw)
        if mulai >= selesai:
            raise ValueError("jam_mulai harus lebih awal daripada jam_selesai")

        kode_mk = str(item.get("kode_mk", "") or "")
        nama_mk = str(
            item.get("nama_mk") or item.get("nama") or item.get("mata_kuliah") or kode_mk
        )
        nims = set(item.get("enrolled_nims") or [])
        enrolled = int(
            item.get(
                "enrolled_count",
                item.get("enrolled", item.get("kuota", len(nims))),
            )
        )
        raw_id = item.get("id")
        return _ScheduleView(
            id=int(raw_id) if raw_id is not None else fallback_idx,
            kode_mk=kode_mk,
            nama_mk=nama_mk,
            hari=normalize_hari(item["hari"]),
            jam_mulai=mulai,
            jam_selesai=selesai,
            ruangan=str(item.get("ruangan_kode") or item.get("ruangan") or "").strip(),
            dosen_id=_resolve_dosen_id(item, fallback_idx),
            dosen_nama=str(item.get("dosen") or item.get("dosen_id") or "-"),
            enrolled_count=enrolled,
            kapasitas=item.get("kapasitas"),
        )

    raise ValueError(f"Tipe jadwal tidak didukung: {type(item).__name__}")


@dataclass
class _CandidateSlot:
    hari_num: int
    hari_nama: str
    start_min: int
    end_min: int
    ruangan: str
    kapasitas: int
    score: float
    disrupted_students: int
    reason: str

    def to_dict(self) -> dict[str, Any]:
        jam_mulai = _fmt_minutes(self.start_min)
        jam_selesai = _fmt_minutes(self.end_min)
        return {
            "hari": self.hari_nama,
            "hari_num": self.hari_num,
            "jam": f"{jam_mulai}-{jam_selesai}",
            "jam_mulai": jam_mulai,
            "jam_selesai": jam_selesai,
            "ruangan": self.ruangan,
            "kapasitas": self.kapasitas,
            "reason": self.reason,
        }


def build_rescheduling_prompt(
    conflicted_schedule: dict[str, Any],
    available_slots: list[dict[str, Any]],
) -> str:
    """Menyusun prompt terstruktur untuk AI Scheduling Assistant."""
    nama = (
        conflicted_schedule.get("nama_mk")
        or conflicted_schedule.get("nama")
        or conflicted_schedule.get("kode_mk")
        or "Mata Kuliah"
    )
    hari = conflicted_schedule.get("hari_nama") or HARI_MAP[
        normalize_hari(conflicted_schedule["hari"])
    ]
    jam = conflicted_schedule.get("jam") or (
        f"{conflicted_schedule.get('jam_mulai')}-{conflicted_schedule.get('jam_selesai')}"
    )
    ruangan = conflicted_schedule.get("ruangan") or conflicted_schedule.get("ruangan_kode")
    enrolled = conflicted_schedule.get("enrolled_count", conflicted_schedule.get("enrolled", 0))
    dosen = conflicted_schedule.get("dosen", "-")

    slots_preview = json.dumps(available_slots[:25], ensure_ascii=False)
    return (
        "Anda adalah scheduling assistant. Diberikan:\n"
        f"- Jadwal bentrok: {nama} ({hari} {jam}, Ruang {ruangan}, {enrolled} mhs, Dosen {dosen})\n"
        f"- Available slots: {slots_preview}\n\n"
        "Rekomendasikan 3 alternatif jadwal yang:\n"
        "1. Ruangan kapasitasnya cukup\n"
        "2. Tidak bentrok dengan jadwal dosen\n"
        "3. Minimal disruption untuk mahasiswa (prioritas pagi/siang)\n"
        'Output format JSON saja: [{"hari": "...", "jam": "HH:MM-HH:MM", "ruangan": "...", "reason": "..."}]'
    )


def _extract_json_array(raw_text: str) -> list[dict[str, Any]]:
    """Mengekstrak array JSON dari respons teks LLM (termasuk blok markdown ```json)."""
    cleaned = raw_text.strip()
    fence_match = re.search(r"```(?:json)?\s*(\[[\s\S]*?\])\s*```", cleaned, re.IGNORECASE)
    if fence_match:
        cleaned = fence_match.group(1)
    else:
        bracket_match = re.search(r"(\[[\s\S]*\])", cleaned)
        if bracket_match:
            cleaned = bracket_match.group(1)
    parsed = json.loads(cleaned)
    if not isinstance(parsed, list):
        raise ValueError("Respons AI bukan list JSON")
    return [item for item in parsed if isinstance(item, dict)]


def _call_llm_raw(prompt: str) -> str | None:
    """Memanggil Gemini atau OpenAI API via httpx jika API key tersedia di environment."""
    if settings.GEMINI_API_KEY:
        model = settings.AI_MODEL or "gemini-2.0-flash"
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent?key={settings.GEMINI_API_KEY}"
        )
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2},
        }
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
        candidates = data.get("candidates") or []
        if candidates:
            parts = (candidates[0].get("content") or {}).get("parts") or []
            if parts and "text" in parts[0]:
                return str(parts[0]["text"])

    if settings.OPENAI_API_KEY:
        model = settings.AI_MODEL or "gpt-4o-mini"
        url = "https://api.openai.com/v1/chat/completions"
        headers = {"Authorization": f"Bearer {settings.OPENAI_API_KEY}"}
        payload = {
            "model": model,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": "Respond only with valid JSON array."},
                {"role": "user", "content": prompt},
            ],
        }
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
        choices = data.get("choices") or []
        if choices:
            return str((choices[0].get("message") or {}).get("content") or "")

    return None


def _normalize_rooms(available_rooms: list[Ruangan | dict[str, Any]]) -> dict[str, int]:
    """Mengonversi daftar ruangan menjadi mapping kode -> kapasitas."""
    rooms: dict[str, int] = {}
    for room in available_rooms:
        if isinstance(room, Ruangan):
            rooms[room.kode] = int(room.kapasitas)
        elif isinstance(room, dict):
            code = str(
                room.get("kode")
                or room.get("kode_ruangan")
                or room.get("ruangan")
                or room.get("nama")
                or ""
            )
            cap = int(room.get("kapasitas") or 0)
            if code and cap > 0:
                rooms[code] = cap
    return rooms


def _normalize_busy_slots(
    student_busy_slots: list[dict[str, Any] | tuple[int | str, int, int]] | None,
) -> dict[int, list[tuple[int, int]]]:
    """Mengelompokkan rentang sibuk mahasiswa per hari dalam satuan menit [start, end)."""
    by_day: dict[int, list[tuple[int, int]]] = {}
    if not student_busy_slots:
        return by_day

    for item in student_busy_slots:
        if isinstance(item, tuple):
            hari_raw, start_min, end_min = item
            hari_num = normalize_hari(hari_raw)
        else:
            hari_num = normalize_hari(item["hari"])
            start_min = (
                int(item["start_min"])
                if "start_min" in item
                else to_minutes(item["jam_mulai"])
            )
            end_min = (
                int(item["end_min"])
                if "end_min" in item
                else to_minutes(item["jam_selesai"])
            )
        if start_min < end_min:
            by_day.setdefault(hari_num, []).append((start_min, end_min))
    return by_day


def _slot_is_conflict_free(
    cand_slot: JadwalSlot,
    enrolled_count: int,
    other_slots: list[JadwalSlot],
    room_capacity: int,
) -> bool:
    """Guardrail deterministik: cek kapasitas cukup dan nol bentrok ruangan/dosen via Sort & Sweep."""
    if enrolled_count > room_capacity:
        return False
    conflicts = detect_conflicts_sweep([*other_slots, cand_slot])
    return not any(cand_slot.id in c.affected for c in conflicts)


def _score_candidate_slots(
    target: _ScheduleView,
    other_slots: list[JadwalSlot],
    rooms_map: dict[str, int],
    *,
    available_slots: list[dict[str, Any]] | None = None,
    student_busy_slots: list[dict[str, Any] | tuple[int | str, int, int]] | None = None,
) -> list[_CandidateSlot]:
    """Menilai dan mengurutkan seluruh slot kandidat yang memenuhi 3 constraint."""
    duration = to_minutes(target.jam_selesai) - to_minutes(target.jam_mulai)
    busy_by_day = _normalize_busy_slots(student_busy_slots)

    raw_candidates: list[tuple[int, int, int, str, int]] = []
    if available_slots is not None:
        for slot in available_slots:
            hari_num = normalize_hari(slot["hari"])
            if "jam_mulai" in slot and "jam_selesai" in slot:
                start_min = to_minutes(slot["jam_mulai"])
                end_min = to_minutes(slot["jam_selesai"])
            elif "jam" in slot and "-" in str(slot["jam"]):
                s_str, e_str = str(slot["jam"]).split("-", 1)
                start_min = to_minutes(s_str)
                end_min = to_minutes(e_str)
            elif "jam" in slot:
                start_min = to_minutes(slot["jam"])
                end_min = start_min + duration
            else:
                continue
            ruangan = str(slot.get("ruangan") or slot.get("kode_ruangan") or slot.get("kode") or "")
            kapasitas = int(slot.get("kapasitas") or rooms_map.get(ruangan, 0))
            if ruangan and kapasitas > 0 and start_min < end_min:
                raw_candidates.append((hari_num, start_min, end_min, ruangan, kapasitas))
    else:
        for hari_num in range(1, 6):  # Senin-Jumat
            for start_min in _DEFAULT_START_MINUTES:
                end_min = start_min + duration
                if end_min > 18 * 60:
                    continue
                for ruangan, kapasitas in sorted(rooms_map.items()):
                    raw_candidates.append((hari_num, start_min, end_min, ruangan, kapasitas))

    scored: list[_CandidateSlot] = []
    seen_keys: set[tuple[int, int, int, str]] = set()
    cand_id = target.id if target.id >= 0 else -999999

    for hari_num, start_min, end_min, ruangan, kapasitas in raw_candidates:
        key = (hari_num, start_min, end_min, ruangan.strip().lower())
        if key in seen_keys:
            continue
        seen_keys.add(key)

        if kapasitas < target.enrolled_count:
            continue

        # Hindari menyarankan kembali slot persis sama dengan slot yang sedang bermasalah
        if (
            hari_num == target.hari
            and start_min == to_minutes(target.jam_mulai)
            and end_min == to_minutes(target.jam_selesai)
            and ruangan.strip().lower() == target.ruangan.strip().lower()
        ):
            continue

        cand_slot = JadwalSlot(
            id=cand_id,
            hari=hari_num,
            jam_mulai=_minutes_to_time(start_min),
            jam_selesai=_minutes_to_time(end_min),
            ruangan_kode=ruangan.strip(),
            dosen_id=target.dosen_id,
        )
        if not _slot_is_conflict_free(cand_slot, target.enrolled_count, other_slots, kapasitas):
            continue

        disrupted = sum(
            1
            for bs, be in busy_by_day.get(hari_num, [])
            if bs < end_min and start_min < be
        )

        # Scoring: prioritas pagi/siang, penalti tinggi jika mengganggu jadwal mahasiswa
        if 7 * 60 <= start_min < 12 * 60:
            time_score = 35.0 if start_min >= 8 * 60 else 28.0
            time_label = "slot pagi optimal"
        elif 12 * 60 <= start_min < 15 * 60:
            time_score = 22.0
            time_label = "slot siang prioritas"
        elif 15 * 60 <= start_min < 17 * 60:
            time_score = 10.0
            time_label = "slot sore"
        else:
            time_score = 2.0
            time_label = "slot akhir hari"

        slack = max(0, kapasitas - target.enrolled_count)
        fit_bonus = max(0.0, 10.0 - slack * 0.15)
        day_bonus = (
            3.0
            if hari_num == target.hari
            else max(0.0, 2.0 - abs(hari_num - target.hari) * 0.4)
        )
        disruption_penalty = disrupted * 50.0
        total_score = time_score + fit_bonus + day_bonus - disruption_penalty

        disruption_note = (
            "0 bentrok jadwal mahasiswa lain"
            if disrupted == 0
            else f"minimal gangguan ({disrupted} irisan kelas mahasiswa)"
        )
        reason = (
            f"Kapasitas {ruangan} ({kapasitas} kursi) cukup untuk {target.enrolled_count} mahasiswa, "
            f"bebas bentrok dosen {target.dosen_nama}, {time_label} dengan {disruption_note}."
        )
        scored.append(
            _CandidateSlot(
                hari_num=hari_num,
                hari_nama=HARI_MAP[hari_num],
                start_min=start_min,
                end_min=end_min,
                ruangan=ruangan,
                kapasitas=kapasitas,
                score=total_score,
                disrupted_students=disrupted,
                reason=reason,
            )
        )

    scored.sort(
        key=lambda c: (-c.score, c.disrupted_students, c.start_min, c.hari_num, c.ruangan)
    )
    return scored


def suggest_alternative_schedules(
    conflicted_schedule: Jadwal | JadwalSlot | dict[str, Any],
    existing_schedules: list[Jadwal | JadwalSlot | dict[str, Any]],
    available_rooms: list[Ruangan | dict[str, Any]],
    *,
    available_slots: list[dict[str, Any]] | None = None,
    student_busy_slots: list[dict[str, Any] | tuple[int | str, int, int]] | None = None,
    top_k: int = 3,
    use_ai: bool = True,
) -> dict[str, Any]:
    """Menghasilkan hingga 3 alternatif jadwal pengganti (Hybrid AI + Constraint Guardrail)."""
    target = _to_schedule_view(conflicted_schedule, fallback_idx=-999999)
    rooms_map = _normalize_rooms(available_rooms)

    other_slots: list[JadwalSlot] = []
    for idx, item in enumerate(existing_schedules, start=1):
        view = _to_schedule_view(item, fallback_idx=idx)
        if view.id == target.id:
            continue
        other_slots.append(view.to_slot())

    valid_candidates = _score_candidate_slots(
        target,
        other_slots,
        rooms_map,
        available_slots=available_slots,
        student_busy_slots=student_busy_slots,
    )

    candidate_dicts = [c.to_dict() for c in valid_candidates]
    target_dict = {
        "kode_mk": target.kode_mk,
        "nama_mk": target.nama_mk,
        "hari": target.hari,
        "hari_nama": HARI_MAP[target.hari],
        "jam": f"{target.jam_mulai.strftime('%H:%M')}-{target.jam_selesai.strftime('%H:%M')}",
        "ruangan": target.ruangan,
        "dosen": target.dosen_nama,
        "enrolled_count": target.enrolled_count,
    }
    prompt_preview = build_rescheduling_prompt(target_dict, candidate_dicts)

    chosen: list[dict[str, Any]] = []
    chosen_keys: set[tuple[int, int, int, str]] = set()
    source = "rule_based_fallback"
    cand_id = target.id if target.id >= 0 else -999999

    ai_configured = bool(settings.GEMINI_API_KEY or settings.OPENAI_API_KEY)
    if use_ai and ai_configured and valid_candidates:
        try:
            raw_ai = _call_llm_raw(prompt_preview)
            if raw_ai:
                ai_items = _extract_json_array(raw_ai)
                for item in ai_items:
                    if len(chosen) >= top_k:
                        break
                    try:
                        hari_num = normalize_hari(item["hari"])
                        jam_str = str(item["jam"])
                        if "-" in jam_str:
                            s_str, e_str = jam_str.split("-", 1)
                            start_min = to_minutes(s_str)
                            end_min = to_minutes(e_str)
                        else:
                            start_min = to_minutes(jam_str)
                            end_min = start_min + (
                                to_minutes(target.jam_selesai) - to_minutes(target.jam_mulai)
                            )
                        ruangan = str(item["ruangan"]).strip()
                        kapasitas = rooms_map.get(ruangan, 0)
                        if kapasitas <= 0 or start_min >= end_min:
                            continue

                        ai_slot = JadwalSlot(
                            id=cand_id,
                            hari=hari_num,
                            jam_mulai=_minutes_to_time(start_min),
                            jam_selesai=_minutes_to_time(end_min),
                            ruangan_kode=ruangan,
                            dosen_id=target.dosen_id,
                        )
                        if not _slot_is_conflict_free(
                            ai_slot, target.enrolled_count, other_slots, kapasitas
                        ):
                            continue

                        key = (hari_num, start_min, end_min, ruangan.lower())
                        if key in chosen_keys:
                            continue
                        chosen_keys.add(key)
                        chosen.append(
                            {
                                "hari": HARI_MAP[hari_num],
                                "hari_num": hari_num,
                                "jam": f"{_fmt_minutes(start_min)}-{_fmt_minutes(end_min)}",
                                "jam_mulai": _fmt_minutes(start_min),
                                "jam_selesai": _fmt_minutes(end_min),
                                "ruangan": ruangan,
                                "kapasitas": kapasitas,
                                "reason": str(
                                    item.get("reason")
                                    or "Direkomendasikan AI & tervalidasi bebas bentrok."
                                ),
                            }
                        )
                    except (KeyError, ValueError, TypeError):
                        continue

                if chosen:
                    source = "ai" if len(chosen) >= top_k else "ai_with_fallback"
        except Exception as exc:
            logger.warning("AI rescheduler gagal, fallback ke algoritma lokal: %s", exc)

    for cand in valid_candidates:
        if len(chosen) >= top_k:
            break
        key = (cand.hari_num, cand.start_min, cand.end_min, cand.ruangan.strip().lower())
        if key not in chosen_keys:
            chosen_keys.add(key)
            chosen.append(cand.to_dict())

    return {
        "source": source,
        "prompt_preview": prompt_preview,
        "recommendations": chosen[:top_k],
    }
