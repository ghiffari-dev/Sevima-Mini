from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time
from typing import Any, Iterable

from app.models.schedule import (
    HARI_MAP,
    JadwalKuliah,
    ScheduleCapacityError,
    ScheduleError,
    normalize_hari,
)
from app.services.interval_tree import IntervalTree, to_minutes


def _parse_time_value(value: time | str) -> time:
    """Mengonversi objek time atau string 'HH:MM' menjadi datetime.time."""
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


@dataclass
class ScheduleRecord:
    """Representasi seragam satu entri jadwal untuk deteksi bentrok 3 dimensi."""

    id: int | str | None
    kode_mk: str
    nama_mk: str
    hari: int
    jam_mulai: time
    jam_selesai: time
    ruangan: str
    dosen: str
    enrolled_count: int = 0
    kapasitas: int | None = None
    enrolled_nims: set[str] = field(default_factory=set)


def to_schedule_record(item: ScheduleRecord | JadwalKuliah | dict[str, Any]) -> ScheduleRecord:
    """Mengonversi ScheduleRecord, ORM JadwalKuliah, atau dict menjadi ScheduleRecord."""
    if isinstance(item, ScheduleRecord):
        hari_num = normalize_hari(item.hari)
        mulai = _parse_time_value(item.jam_mulai)
        selesai = _parse_time_value(item.jam_selesai)
        if mulai >= selesai:
            raise ScheduleError("jam_mulai harus lebih awal daripada jam_selesai")
        return ScheduleRecord(
            id=item.id,
            kode_mk=item.kode_mk,
            nama_mk=item.nama_mk,
            hari=hari_num,
            jam_mulai=mulai,
            jam_selesai=selesai,
            ruangan=item.ruangan,
            dosen=item.dosen,
            enrolled_count=item.enrolled_count,
            kapasitas=item.kapasitas,
            enrolled_nims=set(item.enrolled_nims),
        )

    if isinstance(item, JadwalKuliah):
        mk_nama = item.matakuliah.nama if item.matakuliah is not None else item.kode_mk
        kap = item.ruangan.kapasitas if item.ruangan is not None else None
        return ScheduleRecord(
            id=item.id,
            kode_mk=item.kode_mk,
            nama_mk=mk_nama,
            hari=normalize_hari(item.hari),
            jam_mulai=item.jam_mulai,
            jam_selesai=item.jam_selesai,
            ruangan=item.ruangan_kode,
            dosen=item.dosen,
            enrolled_count=item.enrolled_count,
            kapasitas=kap,
        )

    if isinstance(item, dict):
        jam_mulai_raw = item.get("jam_mulai")
        jam_selesai_raw = item.get("jam_selesai")
        if (jam_mulai_raw is None or jam_selesai_raw is None) and item.get("jam"):
            jam_str = str(item["jam"])
            if "-" in jam_str:
                jam_mulai_raw, jam_selesai_raw = jam_str.split("-", 1)
        if jam_mulai_raw is None or jam_selesai_raw is None:
            raise ScheduleError("Jadwal harus memiliki jam_mulai dan jam_selesai")

        mulai = _parse_time_value(jam_mulai_raw)
        selesai = _parse_time_value(jam_selesai_raw)
        if mulai >= selesai:
            raise ScheduleError("jam_mulai harus lebih awal daripada jam_selesai")

        kode_mk = str(item.get("kode_mk", "") or "")
        nama_mk = str(
            item.get("nama_mk") or item.get("nama") or item.get("mata_kuliah") or kode_mk
        )
        nims = set(item.get("enrolled_nims") or [])
        enrolled = int(item.get("enrolled_count", item.get("enrolled", len(nims))))
        return ScheduleRecord(
            id=item.get("id"),
            kode_mk=kode_mk,
            nama_mk=nama_mk,
            hari=normalize_hari(item["hari"]),
            jam_mulai=mulai,
            jam_selesai=selesai,
            ruangan=str(item.get("ruangan") or item.get("ruangan_kode") or ""),
            dosen=str(item.get("dosen") or ""),
            enrolled_count=enrolled,
            kapasitas=item.get("kapasitas"),
            enrolled_nims=nims,
        )

    raise ScheduleError(f"Tipe data jadwal tidak didukung: {type(item).__name__}")


def record_to_dict(rec: ScheduleRecord) -> dict[str, Any]:
    """Mengubah ScheduleRecord menjadi dictionary serializable untuk API dan detail bentrok."""
    mulai_str = rec.jam_mulai.strftime("%H:%M")
    selesai_str = rec.jam_selesai.strftime("%H:%M")
    return {
        "id": rec.id,
        "kode_mk": rec.kode_mk,
        "nama_mk": rec.nama_mk,
        "hari": rec.hari,
        "hari_nama": HARI_MAP[rec.hari],
        "jam_mulai": mulai_str,
        "jam_selesai": selesai_str,
        "jam": f"{mulai_str}-{selesai_str}",
        "ruangan": rec.ruangan,
        "dosen": rec.dosen,
        "enrolled_count": rec.enrolled_count,
        "kapasitas": rec.kapasitas,
    }


def check_room_capacity(enrolled: int, capacity: int, ruangan: str) -> None:
    """Memastikan jumlah mahasiswa terdaftar tidak melebihi kapasitas ruangan."""
    if enrolled > capacity:
        raise ScheduleCapacityError(
            f"Jumlah mahasiswa ({enrolled}) melebihi kapasitas ruangan {ruangan} ({capacity})"
        )


def detect_schedule_conflict(
    schedules: Iterable[ScheduleRecord | JadwalKuliah | dict[str, Any]],
    *,
    include_general_overlap: bool = False,
) -> list[dict[str, Any]]:
    """Mendeteksi bentrok jadwal 3 dimensi (waktu-ruangan-dosen) menggunakan Interval Tree.

    Untuk setiap hari, membangun IntervalTree dari rentang menit [jam_mulai, jam_selesai).
    Mengembalikan daftar konflik bertipe:
    - 'room_conflict': hari sama, jam overlap, ruangan sama
    - 'lecturer_conflict': hari sama, jam overlap, dosen sama
    - 'time_overlap': hari sama, jam overlap untuk mahasiswa/MK yang sama (atau umum bila flag aktif)
    """
    records = [to_schedule_record(s) for s in schedules]
    by_day: dict[int, list[ScheduleRecord]] = {}
    for rec in records:
        by_day.setdefault(rec.hari, []).append(rec)

    conflicts: list[dict[str, Any]] = []
    for hari in sorted(by_day):
        tree = IntervalTree()
        for rec in by_day[hari]:
            tree.insert(to_minutes(rec.jam_mulai), to_minutes(rec.jam_selesai), rec)

        for s1, s2 in tree.find_all_overlapping_pairs():
            s1_dict = record_to_dict(s1)
            s2_dict = record_to_dict(s2)
            specific_emitted = False

            r1 = s1.ruangan.strip().lower()
            r2 = s2.ruangan.strip().lower()
            if r1 and r1 == r2:
                conflicts.append(
                    {
                        "type": "room_conflict",
                        "affected_schedules": [s1_dict, s2_dict],
                        "detail": (
                            f"Bentrok ruangan {s1.ruangan} pada {HARI_MAP[hari]} "
                            f"({s1_dict['jam']} vs {s2_dict['jam']})"
                        ),
                    }
                )
                specific_emitted = True

            d1 = s1.dosen.strip().lower()
            d2 = s2.dosen.strip().lower()
            if d1 and d1 == d2:
                conflicts.append(
                    {
                        "type": "lecturer_conflict",
                        "affected_schedules": [s1_dict, s2_dict],
                        "detail": (
                            f"Bentrok dosen {s1.dosen} pada {HARI_MAP[hari]} "
                            f"({s1_dict['jam']} vs {s2_dict['jam']})"
                        ),
                    }
                )
                specific_emitted = True

            shared_nims = sorted(s1.enrolled_nims & s2.enrolled_nims)
            same_course = bool(
                s1.kode_mk
                and s2.kode_mk
                and s1.kode_mk.strip().lower() == s2.kode_mk.strip().lower()
            )
            if shared_nims or same_course or (include_general_overlap and not specific_emitted):
                if shared_nims:
                    reason = (
                        f"Bentrok waktu mahasiswa ({', '.join(shared_nims)}) pada {HARI_MAP[hari]} "
                        f"({s1_dict['jam']} vs {s2_dict['jam']})"
                    )
                elif same_course:
                    reason = (
                        f"Bentrok waktu mata kuliah sama ({s1.kode_mk}) pada {HARI_MAP[hari]} "
                        f"({s1_dict['jam']} vs {s2_dict['jam']})"
                    )
                else:
                    reason = (
                        f"Irisan waktu jadwal pada {HARI_MAP[hari]} "
                        f"({s1_dict['jam']} vs {s2_dict['jam']})"
                    )
                conflicts.append(
                    {
                        "type": "time_overlap",
                        "affected_schedules": [s1_dict, s2_dict],
                        "detail": reason,
                    }
                )

    return conflicts
