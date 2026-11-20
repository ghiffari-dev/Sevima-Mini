"""Functional core modul presensi: aturan waktu, rotasi QR, geofence, & persentase.

Seluruh fungsi di sini murni (tanpa DB / jam sistem) agar mudah diuji dengan
`pytest.mark.parametrize` dan `Hypothesis`. Jam selalu disuntikkan dari luar.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
import hashlib
import hmac
import math
from zoneinfo import ZoneInfo

from app.models.attendance import AttendanceStatus

EARTH_RADIUS_M = 6_371_008.8
TWO_PLACES = Decimal("0.01")


@dataclass(frozen=True)
class AttendancePolicy:
    """Kebijakan waktu presensi (dibaca dari Settings, bisa diganti di test)."""

    timezone: str = "Asia/Jakarta"
    rotate_seconds: int = 120
    grace_windows: int = 1
    open_early_minutes: int = 15
    on_time_minutes: int = 15
    late_max_minutes: int = 30
    min_percent: Decimal = Decimal("75")
    total_pertemuan: int = 14

    def __post_init__(self) -> None:
        if self.rotate_seconds <= 0:
            raise ValueError("rotate_seconds harus > 0")
        if self.grace_windows < 0:
            raise ValueError("grace_windows tidak boleh negatif")
        if not 0 <= self.on_time_minutes <= self.late_max_minutes:
            raise ValueError("Syarat 0 <= on_time_minutes <= late_max_minutes")

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


# ---------------------------------------------------------------------------
# Waktu kuliah
# ---------------------------------------------------------------------------


def lecture_start_utc(tanggal: date, jam_mulai: time, tz: ZoneInfo) -> datetime:
    """Menggabungkan tanggal + jam mulai lokal (WIB) menjadi datetime UTC."""
    return datetime.combine(tanggal, jam_mulai, tzinfo=tz).astimezone(timezone.utc)


def local_date(now_utc: datetime, tz: ZoneInfo) -> date:
    """Tanggal lokal (WIB) dari sebuah instan UTC — dipakai untuk cek 'hari ini ada kuliah'."""
    return now_utc.astimezone(tz).date()


def iso_hari(tanggal: date) -> int:
    """Kode hari 1=Senin .. 7=Minggu (selaras kolom jadwal.hari 1..6)."""
    return tanggal.isoweekday()


def determine_attendance_status(
    lecture_start: datetime,
    now: datetime,
    on_time_minutes: int = 15,
    late_max_minutes: int = 30,
) -> AttendanceStatus | None:
    """Menentukan status scan relatif terhadap jam mulai kuliah.

    - `now <= mulai + on_time`              -> hadir (termasuk scan sebelum kuliah dimulai)
    - `mulai + on_time < now <= mulai + max` -> terlambat
    - `now > mulai + max`                   -> None (window presensi sudah tutup)
    """
    offset = now - lecture_start
    if offset <= timedelta(minutes=on_time_minutes):
        return AttendanceStatus.HADIR
    if offset <= timedelta(minutes=late_max_minutes):
        return AttendanceStatus.TERLAMBAT
    return None


def can_open_session(
    lecture_start: datetime,
    lecture_end: datetime,
    now: datetime,
    open_early_minutes: int = 15,
) -> bool:
    """Dosen hanya boleh membuka presensi dari `mulai - open_early` s.d. jam selesai kuliah."""
    return lecture_start - timedelta(minutes=open_early_minutes) <= now <= lecture_end


# ---------------------------------------------------------------------------
# Rotasi QR (anti-replay & anti titip-absen)
# ---------------------------------------------------------------------------


def window_index(opened_at: datetime, now: datetime, rotate_seconds: int) -> int:
    """Indeks jendela rotasi QR sejak sesi dibuka (0, 1, 2, ...)."""
    elapsed = (now - opened_at).total_seconds()
    if elapsed < 0:
        return 0
    return int(elapsed // rotate_seconds)


def window_bounds(
    opened_at: datetime, window: int, rotate_seconds: int
) -> tuple[datetime, datetime]:
    """Rentang [mulai, akhir) sebuah jendela rotasi."""
    start = opened_at + timedelta(seconds=window * rotate_seconds)
    return start, start + timedelta(seconds=rotate_seconds)


def is_window_accepted(token_window: int, current_window: int, grace_windows: int) -> bool:
    """Token diterima bila berasal dari jendela saat ini atau maks. `grace` jendela sebelumnya."""
    if token_window < 0 or token_window > current_window:
        return False
    return current_window - token_window <= grace_windows


def qr_nonce(secret: str, session_id: int, window: int) -> str:
    """Nonce deterministik HMAC-SHA256(secret_sesi, 'sid:window') — unik per sesi & jendela."""
    msg = f"{session_id}:{window}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()[:32]


def verify_qr_nonce(secret: str, session_id: int, window: int, nonce: str) -> bool:
    return hmac.compare_digest(qr_nonce(secret, session_id, window), str(nonce or ""))


# ---------------------------------------------------------------------------
# Geofence
# ---------------------------------------------------------------------------


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Jarak lingkaran besar (meter) antara dua koordinat WGS84."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def valid_coordinate(lat: float | None, lon: float | None) -> bool:
    if lat is None or lon is None:
        return False
    if any(isinstance(v, bool) for v in (lat, lon)):
        return False
    try:
        lat_f, lon_f = float(lat), float(lon)
    except (TypeError, ValueError):
        return False
    if math.isnan(lat_f) or math.isnan(lon_f):
        return False
    return -90.0 <= lat_f <= 90.0 and -180.0 <= lon_f <= 180.0


# ---------------------------------------------------------------------------
# Persentase & risiko
# ---------------------------------------------------------------------------


def attendance_percentage(attended: int, total: int) -> Decimal:
    """Persentase kehadiran `Decimal` 2 desimal ROUND_HALF_UP.

    Belum ada pertemuan (total 0) => 100.00 karena belum ada absen yang terjadi.
    """
    if total < 0 or attended < 0:
        raise ValueError("attended/total tidak boleh negatif")
    if attended > total:
        raise ValueError("attended tidak boleh melebihi total pertemuan")
    if total == 0:
        return Decimal("100.00")
    return (Decimal(attended) * Decimal(100) / Decimal(total)).quantize(
        TWO_PLACES, rounding=ROUND_HALF_UP
    )


def max_allowed_absences(total_pertemuan: int, min_percent: Decimal) -> int:
    """Jatah absen maksimum per semester agar presensi akhir tetap >= min_percent."""
    if total_pertemuan <= 0:
        return 0
    min_hadir = math.ceil(Decimal(total_pertemuan) * min_percent / Decimal(100))
    return max(0, total_pertemuan - int(min_hadir))


def risk_level(
    alpha: int,
    held: int,
    total_pertemuan: int,
    min_percent: Decimal,
) -> str:
    """Klasifikasi early-warning: `kritis` | `berisiko` | `aman`.

    - kritis   : absen sudah melebihi jatah semester (mustahil lagi mencapai min_percent)
    - berisiko : sisa jatah absen tinggal <= 1 kali ATAU persentase berjalan < min_percent
    - aman     : selain itu
    """
    attended = max(0, held - alpha)
    persen = attendance_percentage(attended, held) if held else Decimal("100.00")
    jatah = max_allowed_absences(max(total_pertemuan, held), min_percent)
    if alpha > jatah:
        return "kritis"
    if jatah - alpha <= 1 or persen < min_percent:
        return "berisiko"
    return "aman"
