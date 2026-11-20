from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import time
from itertools import combinations
from typing import Any, Callable, Iterable, Literal, Protocol

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.krs import KRS, KRSDetail
from app.models.schedule import (
    Kelas,
    Ruangan,
    ScheduleCapacityError,
    ScheduleError,
    normalize_hari,
)

ConflictType = Literal["room_conflict", "lecturer_conflict"]


def to_minutes(value: time | str) -> int:
    """Mengonversi objek datetime.time atau string 'HH:MM' menjadi total menit sejak 00:00."""
    if isinstance(value, time):
        return value.hour * 60 + value.minute
    cleaned = str(value).strip()
    parts = cleaned.split(":")
    if len(parts) < 2:
        raise ScheduleError(f"Format jam tidak valid: {value}")
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError as exc:
        raise ScheduleError(f"Format jam tidak valid: {value}") from exc
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ScheduleError(f"Jam/menit di luar rentang valid: {value}")
    return hour * 60 + minute


def parse_time_value(value: time | str) -> time:
    """Mengonversi objek time atau string 'H:MM'/'HH:MM' menjadi datetime.time."""
    if isinstance(value, time):
        return value
    cleaned = str(value).strip()
    parts = cleaned.split(":")
    if len(parts) < 2:
        raise ScheduleError(f"Format jam tidak valid: {value}")
    try:
        return time(int(parts[0]), int(parts[1]))
    except ValueError as exc:
        raise ScheduleError(f"Format jam tidak valid: {value}") from exc


def pasangan(a: int, b: int) -> tuple[int, int]:
    """Mengurutkan dua ID jadwal agar pasangan (A, B) dan (B, A) menghasilkan konflik identik."""
    return (a, b) if a <= b else (b, a)


@dataclass(frozen=True)
class Conflict:
    """Representasi konflik jadwal immutable (hashable untuk set & Counter)."""

    type: ConflictType
    affected: tuple[int, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "affected": list(self.affected),
        }


class JadwalLike(Protocol):
    """Protokol bersama antara ORM Jadwal dan dataclass ringan JadwalSlot."""

    id: int
    hari: int
    jam_mulai: time
    jam_selesai: time
    ruangan_kode: str
    dosen_id: int


@dataclass(frozen=True)
class JadwalSlot:
    """Versi ringan Jadwal tanpa ketergantungan ORM database."""

    id: int
    hari: int
    jam_mulai: time
    jam_selesai: time
    ruangan_kode: str
    dosen_id: int


def _coerce_jadwal_list(schedules: Iterable[JadwalLike | dict[str, Any]]) -> list[JadwalLike]:
    """Memastikan setiap item dapat diakses sebagai JadwalLike (ORM Jadwal / JadwalSlot)."""
    result: list[JadwalLike] = []
    for idx, item in enumerate(schedules, start=1):
        if isinstance(item, dict):
            jam_mulai_raw = item.get("jam_mulai")
            jam_selesai_raw = item.get("jam_selesai")
            if (jam_mulai_raw is None or jam_selesai_raw is None) and item.get("jam"):
                jam_str = str(item["jam"])
                if "-" in jam_str:
                    jam_mulai_raw, jam_selesai_raw = jam_str.split("-", 1)
            if jam_mulai_raw is None or jam_selesai_raw is None:
                raise ScheduleError("Jadwal harus memiliki jam_mulai dan jam_selesai")

            mulai = parse_time_value(jam_mulai_raw)
            selesai = parse_time_value(jam_selesai_raw)
            if mulai >= selesai:
                raise ScheduleError("jam_mulai harus lebih awal daripada jam_selesai")

            raw_id = item.get("id")
            item_id = int(raw_id) if raw_id is not None else idx
            raw_dosen = item.get("dosen_id")
            if raw_dosen is None:
                dosen_val = item.get("dosen")
                if isinstance(dosen_val, int):
                    raw_dosen = dosen_val
                elif dosen_val is not None and str(dosen_val).strip():
                    raw_dosen = abs(hash(str(dosen_val).strip().lower())) % 1_000_000_000 + 1
                else:
                    # Gunakan nilai negatif unik agar entri tanpa dosen pada input dict tidak saling bentrok
                    raw_dosen = -idx

            result.append(
                JadwalSlot(
                    id=item_id,
                    hari=normalize_hari(item["hari"]),
                    jam_mulai=mulai,
                    jam_selesai=selesai,
                    ruangan_kode=str(
                        item.get("ruangan_kode") or item.get("ruangan") or ""
                    ).strip(),
                    dosen_id=int(raw_dosen),
                )
            )
        else:
            result.append(item)
    return result


def detect_conflicts_naive(
    schedules: Iterable[JadwalLike | dict[str, Any]],
) -> list[Conflict]:
    """Versi naif O(n^2) memakai itertools.combinations sebagai acuan (oracle) kebenaran."""
    items = _coerce_jadwal_list(schedules)
    conflicts: list[Conflict] = []
    for a, b in combinations(items, 2):
        if a.hari != b.hari:
            continue
        if not (a.jam_mulai < b.jam_selesai and b.jam_mulai < a.jam_selesai):
            continue
        if a.ruangan_kode != "" and a.ruangan_kode == b.ruangan_kode:
            conflicts.append(Conflict("room_conflict", pasangan(a.id, b.id)))
        if a.dosen_id is not None and a.dosen_id == b.dosen_id:
            conflicts.append(Conflict("lecturer_conflict", pasangan(a.id, b.id)))
    return conflicts


ATURAN_KELOMPOK: dict[ConflictType, Callable[[JadwalLike], tuple[Any, ...]]] = {
    "room_conflict": lambda j: (j.hari, j.ruangan_kode),
    "lecturer_conflict": lambda j: (j.hari, j.dosen_id),
}


def detect_conflicts_sweep(
    schedules: Iterable[JadwalLike | dict[str, Any]],
) -> list[Conflict]:
    """Versi teroptimasi O(n log n + k): Grouping per dimensi + Sort & Sweep half-open [mulai, selesai)."""
    items = _coerce_jadwal_list(schedules)
    conflicts: list[Conflict] = []

    for ctype, key_fn in ATURAN_KELOMPOK.items():
        groups: dict[tuple[Any, ...], list[JadwalLike]] = defaultdict(list)
        for item in items:
            dim_key = key_fn(item)
            if dim_key[1] is None or dim_key[1] == "":
                continue
            groups[dim_key].append(item)

        for group_items in groups.values():
            if len(group_items) < 2:
                continue
            ordered = sorted(
                group_items,
                key=lambda j: (j.jam_mulai, j.jam_selesai, j.id),
            )
            aktif: list[JadwalLike] = []
            for cur in ordered:
                # Interval setengah terbuka: > (bukan >=) agar kuliah bersambung (mis. 09:40) tidak bentrok
                aktif = [a for a in aktif if a.jam_selesai > cur.jam_mulai]
                for a in aktif:
                    conflicts.append(Conflict(ctype, pasangan(a.id, cur.id)))
                aktif.append(cur)

    return conflicts


detect_schedule_conflict = detect_conflicts_sweep


def check_room_capacity(dibutuhkan: int, kapasitas: int, ruangan_kode: str) -> None:
    """Memastikan kebutuhan kursi tidak melebihi kapasitas ruangan (409 Conflict jika penuh)."""
    if dibutuhkan > kapasitas:
        raise ScheduleCapacityError(
            f"Kapasitas ruangan {ruangan_kode} ({kapasitas} kursi) tidak cukup: "
            f"dibutuhkan {dibutuhkan} kursi"
        )


def cek_kapasitas(db: Session, ruangan: Ruangan, kelas: Kelas) -> None:
    """Menghitung peserta terdaftar pada KRSDetail dan membandingkan max(kuota, terdaftar) <= kapasitas."""
    stmt = (
        select(func.count(KRSDetail.id))
        .join(KRS, KRSDetail.krs_id == KRS.id)
        .where(
            KRS.semester == kelas.semester,
            or_(
                KRSDetail.kelas_id == kelas.id,
                (KRSDetail.kelas_id.is_(None)) & (KRSDetail.kode_mk == kelas.kode_mk),
            ),
        )
    )
    terdaftar = int(db.scalar(stmt) or 0)
    dibutuhkan = max(kelas.kuota, terdaftar)
    if dibutuhkan > ruangan.kapasitas:
        raise ScheduleCapacityError(
            f"Kapasitas ruangan {ruangan.kode} ({ruangan.kapasitas} kursi) tidak cukup: "
            f"dibutuhkan {dibutuhkan} kursi (kuota kelas={kelas.kuota}, terdaftar={terdaftar})"
        )
