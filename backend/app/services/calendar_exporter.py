from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.models.schedule import HARI_MAP, Jadwal

SEMESTER_DATE_RANGES: dict[str, tuple[date, date]] = {
    "20251": (date(2025, 9, 1), date(2025, 12, 20)),
    "20252": (date(2026, 2, 2), date(2026, 5, 23)),
}


def _resolve_tz(tz_name: str) -> tzinfo:
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        if tz_name == "Asia/Jakarta":
            return timezone(timedelta(hours=7))
        return timezone.utc


def _escape_ics_text(text: str) -> str:
    return (
        str(text)
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


def first_meeting_date(semester_start: date, hari: int) -> date:
    """Menghitung tanggal pertemuan pertama berdasarkan tanggal awal semester dan hari (1=Senin..6=Sabtu)."""
    target_weekday = int(hari) - 1
    offset = (target_weekday - semester_start.weekday()) % 7
    return semester_start + timedelta(days=offset)


def _resolve_semester_dates(
    schedules: list[Jadwal],
    semester_start: date | None,
    semester_end: date | None,
) -> tuple[date, date]:
    if semester_start is not None and semester_end is not None:
        return semester_start, semester_end

    sem_code = "20251"
    for j in schedules:
        if j.kelas and j.kelas.semester:
            sem_code = j.kelas.semester
            break

    default_start, default_end = SEMESTER_DATE_RANGES.get(
        sem_code, (date(2025, 9, 1), date(2025, 12, 20))
    )
    resolved_start = semester_start or default_start
    resolved_end = semester_end or (
        resolved_start + timedelta(weeks=16) if semester_start else default_end
    )
    return resolved_start, resolved_end


def export_schedules_to_ics(
    schedules: list[Jadwal],
    *,
    semester_start: date | None = None,
    semester_end: date | None = None,
    tz_name: str = "Asia/Jakarta",
) -> str:
    """Mengekspor daftar Jadwal ke format iCalendar RFC 5545 (.ics) dengan CRLF, UID stabil, RRULE UNTIL UTC, & SEQUENCE."""
    start_date, end_date = _resolve_semester_dates(
        schedules, semester_start, semester_end
    )
    local_tz = _resolve_tz(tz_name)
    now_utc = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    # RFC 5545: jika DTSTART memakai TZID, nilai UNTIL pada RRULE wajib dalam UTC (akhiran Z)
    until_local = datetime.combine(end_date, time(23, 59, 59), tzinfo=local_tz)
    until_utc = until_local.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    lines: list[str] = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Sevima-Mini//Jadwal Kuliah//ID",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]
    if tz_name == "Asia/Jakarta":
        lines.extend(
            [
                "BEGIN:VTIMEZONE",
                "TZID:Asia/Jakarta",
                "BEGIN:STANDARD",
                "DTSTART:19700101T000000",
                "TZOFFSETFROM:+0700",
                "TZOFFSETTO:+0700",
                "TZNAME:WIB",
                "END:STANDARD",
                "END:VTIMEZONE",
            ]
        )

    for jadwal in schedules:
        first_dt = first_meeting_date(start_date, jadwal.hari)
        kelas = jadwal.kelas
        mk = kelas.matakuliah if kelas else None
        ruangan = jadwal.ruangan
        dosen = jadwal.dosen

        kode_mk = kelas.kode_mk if kelas else "MK"
        nama_mk = mk.nama if mk else kode_mk
        nama_kelas = kelas.nama_kelas if kelas else "-"
        dosen_nama = dosen.nama if dosen else "-"
        ruangan_label = (
            f"{ruangan.kode} ({ruangan.gedung})"
            if ruangan and ruangan.gedung
            else (ruangan.kode if ruangan else jadwal.ruangan_kode)
        )
        hari_nama = HARI_MAP.get(jadwal.hari, str(jadwal.hari))
        seq = int(getattr(jadwal, "sequence", 0) or 0)

        dtstart_str = f"{first_dt.strftime('%Y%m%d')}T{jadwal.jam_mulai.strftime('%H%M%S')}"
        dtend_str = f"{first_dt.strftime('%Y%m%d')}T{jadwal.jam_selesai.strftime('%H%M%S')}"

        summary = _escape_ics_text(f"{kode_mk} - {nama_mk} (Kelas {nama_kelas})")
        location = _escape_ics_text(ruangan_label)
        description = _escape_ics_text(
            f"Dosen: {dosen_nama} | Hari: {hari_nama} | Jam: {jadwal.jam_mulai.strftime('%H:%M')}-{jadwal.jam_selesai.strftime('%H:%M')}"
        )

        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:jadwal-{jadwal.id}@sevima-mini.ac.id",
                f"DTSTAMP:{now_utc}",
                f"DTSTART;TZID={tz_name}:{dtstart_str}",
                f"DTEND;TZID={tz_name}:{dtend_str}",
                f"RRULE:FREQ=WEEKLY;UNTIL={until_utc}",
                f"SEQUENCE:{seq}",
                f"SUMMARY:{summary}",
                f"LOCATION:{location}",
                f"DESCRIPTION:{description}",
                "END:VEVENT",
            ]
        )

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"
