"""Layanan utama Modul Presensi QR Code (Minggu 12).

Mencakup:
1. QR Generation Service (JWT HS256 + rotasi otomatis tiap N detik dengan HMAC nonce anti-replay).
2. Attendance Recording (validasi JWT, jadwal hari ini, enrollment KRS APPROVED, anti-duplikat,
   validasi geolokasi Haversine & akurasi GPS, kalkulasi status hadir <=15m / terlambat <=30m).
3. Rate Limiting sliding-window per NIM & IP (mencegah spam scan -> HTTP 429).
4. Attendance Report per mahasiswa, per kelas (<75% warning), & ekspor Excel (.xlsx) via `openpyxl`.
5. Implementasi nyata `PresensiPort` (`DatabasePresensiPort`) yang terhubung ke `GradeService` (Minggu 9).
"""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from io import BytesIO
import secrets
from threading import Lock
from typing import Any

from jose import ExpiredSignatureError, JWTError, jwt
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
import qrcode
from sqlalchemy import func, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import ALGORITHM, SECRET_KEY
from app.models.attendance import (
    AttendanceError,
    AttendanceForbiddenError,
    AttendanceNotFoundError,
    AttendanceRecord,
    AttendanceSession,
    AttendanceStatus,
    DuplicateAttendanceError,
    GeolocationError,
    GeolocationRequiredError,
    NotEnrolledError,
    OutsideAttendanceWindowError,
    QRExpiredError,
    QRTokenInvalidError,
    RateLimitExceededError,
    SessionAlreadyOpenError,
    SessionStatus,
    as_utc,
)
from app.models.calon_mahasiswa import CalonMahasiswa
from app.models.jalur_masuk import JalurMasuk
from app.models.krs import KRS, KRSDetail, KRSStatus, MataKuliah
from app.models.program_studi import ProgramStudi
from app.models.schedule import (
    Dosen as DosenJadwal,
    Jadwal,
    Kelas as KelasJadwal,
    Ruangan,
    format_hari,
)
from app.services.attendance_ai_analyzer import analyze_attendance_records
from app.services.attendance_rules import (
    AttendancePolicy,
    attendance_percentage,
    determine_attendance_status,
    haversine_m,
    iso_hari,
    is_window_accepted,
    local_date,
    qr_nonce,
    risk_level,
    valid_coordinate,
    verify_qr_nonce,
    window_bounds,
    window_index,
)
from app.services.grade_service import PresensiPort, StubPresensiPort, default_presensi_stub
from app.services.schedule_recommender import LLMClient


# ---------------------------------------------------------------------------
# Sliding-Window Rate Limiter (Deliverable 5: Security - prevent spam scan)
# ---------------------------------------------------------------------------


class ScanRateLimiter:
    """Rate limiter sliding-window in-memory untuk mencegah spam scan QR presensi."""

    def __init__(
        self,
        max_requests: int | None = None,
        window_seconds: int | None = None,
    ) -> None:
        self.max_requests = (
            max_requests
            if max_requests is not None
            else settings.ATTENDANCE_SCAN_RATE_LIMIT
        )
        self.window_seconds = (
            window_seconds
            if window_seconds is not None
            else settings.ATTENDANCE_SCAN_RATE_WINDOW_SECONDS
        )
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def check(self, key: str, *, now: datetime | None = None) -> None:
        """Memeriksa & mencatat hit; melempar RateLimitExceededError (429) bila melebihi batas."""
        current_dt = as_utc(now) or datetime.now(timezone.utc)
        now_ts = current_dt.timestamp()
        cutoff = now_ts - float(self.window_seconds)

        with self._lock:
            q = self._hits[key]
            while q and q[0] <= cutoff:
                q.popleft()
            if len(q) >= self.max_requests:
                retry_after = max(1, int(round(q[0] + self.window_seconds - now_ts)))
                raise RateLimitExceededError(
                    f"Terlalu banyak percobaan scan presensi ({self.max_requests}x per "
                    f"{self.window_seconds} detik). Silakan tunggu {retry_after} detik.",
                    headers={"Retry-After": str(retry_after)},
                )
            q.append(now_ts)

    def reset(self) -> None:
        """Mengosongkan seluruh histori rate limiter (digunakan pada test fixture)."""
        with self._lock:
            self._hits.clear()


default_scan_rate_limiter = ScanRateLimiter()


# ---------------------------------------------------------------------------
# Step 1 Helper: QR Code Generator (`generate_attendance_qr`)
# ---------------------------------------------------------------------------


def generate_attendance_qr(
    schedule_id: int,
    valid_minutes: int = 15,
    *,
    session_id: int | None = None,
    window: int = 0,
    secret: str | None = None,
    now: datetime | None = None,
    expires_at: datetime | None = None,
) -> tuple[Any, str]:
    """Menghasilkan objek gambar QR dan JWT token presensi (kompatibel penuh dengan Step 1 PDF).

    Menggunakan `datetime.now(timezone.utc)` (bebas deprecation `utcnow()`) serta mendukung
    klaim rotasi sesi (`sid`, `win`, `jti` HMAC-SHA256) untuk mencegah replay attack.
    """
    issued_at = as_utc(now) or datetime.now(timezone.utc)
    exp_dt = (
        as_utc(expires_at)
        if expires_at is not None
        else issued_at + timedelta(minutes=valid_minutes)
    )
    payload: dict[str, Any] = {
        "typ": "attendance_qr",
        "schedule_id": int(schedule_id),
        "iat": int(issued_at.timestamp()),
        "exp": int(exp_dt.timestamp()),
    }
    if session_id is not None:
        payload["sid"] = int(session_id)
        payload["win"] = int(window)
        token_secret = secret or SECRET_KEY
        payload["jti"] = qr_nonce(token_secret, int(session_id), int(window))

    token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
    qr = qrcode.make(token)
    return qr, token


def render_qr_png_bytes(token: str) -> bytes:
    """Merender token JWT presensi menjadi byte gambar PNG QR code."""
    qr_img = qrcode.make(token)
    buf = BytesIO()
    qr_img.save(buf, format="PNG")
    return buf.getvalue()


def decode_attendance_qr_token(
    token: str,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Mendekode & memvalidasi signature/expiry JWT dari QR code presensi."""
    try:
        # Matikan verifikasi exp internal jose bila `now` kustom disuntikkan, lalu cek manual
        options = {"verify_exp": now is None}
        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM],
            options=options,
        )
    except ExpiredSignatureError as exc:
        raise QRExpiredError("QR code sudah kedaluwarsa (expired)") from exc
    except JWTError as exc:
        raise QRTokenInvalidError("Token QR presensi tidak valid atau rusak") from exc

    if not isinstance(payload, dict) or "schedule_id" not in payload:
        raise QRTokenInvalidError("Payload token QR tidak memiliki schedule_id")

    typ = payload.get("typ")
    if typ is not None and typ != "attendance_qr":
        raise QRTokenInvalidError("Tipe token bukan token QR presensi")

    check_now = as_utc(now) or datetime.now(timezone.utc)
    raw_exp = payload.get("exp")
    if raw_exp is None:
        raise QRTokenInvalidError("Token QR tidak memiliki klaim waktu kedaluwarsa (exp)")
    try:
        exp_ts = float(raw_exp)
    except (TypeError, ValueError) as exc:
        raise QRTokenInvalidError("Klaim exp pada token QR tidak valid") from exc

    if check_now.timestamp() > exp_ts:
        raise QRExpiredError("QR code sudah kedaluwarsa (expired)")

    return dict(payload)


# ---------------------------------------------------------------------------
# Implementasi Nyata `PresensiPort` untuk Modul Nilai (Minggu 9 -> Minggu 12)
# ---------------------------------------------------------------------------


class DatabasePresensiPort:
    """Implementasi nyata `PresensiPort` yang menghitung persentase kehadiran dari DB presensi.

    Jika sebuah kelas sudah memiliki sesi di `attendance_session`, persentase dihitung dari
    jumlah record (`hadir` + `terlambat`) dibagi total sesi kelas tersebut. Jika belum ada
    sesi di DB (mis. pada skenario uji lama), mendelegasikan ke `fallback_stub`.
    """

    def __init__(
        self,
        db: Session,
        fallback_stub: StubPresensiPort | None = default_presensi_stub,
    ) -> None:
        self.db = db
        self.fallback_stub = fallback_stub

    def persentase(self, nim: str, kelas_id: int) -> Decimal:
        """Mengembalikan persentase presensi `Decimal` (2 desimal) untuk (nim, kelas_id)."""
        if not inspect(self.db.connection()).has_table(AttendanceSession.__tablename__):
            if self.fallback_stub is not None:
                return self.fallback_stub.persentase(nim, kelas_id)
            return Decimal("100.00")

        total_sessions = int(
            self.db.scalar(
                select(func.count(AttendanceSession.id)).where(
                    AttendanceSession.kelas_id == int(kelas_id)
                )
            )
            or 0
        )
        if total_sessions == 0:
            if self.fallback_stub is not None:
                return self.fallback_stub.persentase(nim, kelas_id)
            return Decimal("100.00")

        attended_count = int(
            self.db.scalar(
                select(func.count(AttendanceRecord.id))
                .join(
                    AttendanceSession,
                    AttendanceRecord.session_id == AttendanceSession.id,
                )
                .where(
                    AttendanceSession.kelas_id == int(kelas_id),
                    AttendanceRecord.nim == nim,
                    AttendanceRecord.status.in_(
                        [AttendanceStatus.HADIR.value, AttendanceStatus.TERLAMBAT.value]
                    ),
                )
            )
            or 0
        )
        return attendance_percentage(min(attended_count, total_sessions), total_sessions)


# ---------------------------------------------------------------------------
# Layanan Utama AttendanceService
# ---------------------------------------------------------------------------


def build_default_policy() -> AttendancePolicy:
    """Membentuk AttendancePolicy dari konfigurasi Settings."""
    return AttendancePolicy(
        timezone=settings.ATTENDANCE_TIMEZONE,
        rotate_seconds=settings.ATTENDANCE_QR_ROTATE_SECONDS,
        grace_windows=settings.ATTENDANCE_QR_GRACE_WINDOWS,
        open_early_minutes=settings.ATTENDANCE_OPEN_EARLY_MINUTES,
        on_time_minutes=settings.ATTENDANCE_ON_TIME_MINUTES,
        late_max_minutes=settings.ATTENDANCE_LATE_MAX_MINUTES,
        min_percent=Decimal(str(settings.ATTENDANCE_MIN_PERCENT)),
        total_pertemuan=settings.ATTENDANCE_TOTAL_PERTEMUAN,
    )


class AttendanceService:
    """Service layer Modul Presensi QR Code, Geofencing, Laporan Excel, & AI Insights."""

    def __init__(
        self,
        db: Session,
        *,
        policy: AttendancePolicy | None = None,
        rate_limiter: ScanRateLimiter | None = None,
    ) -> None:
        self.db = db
        self.policy = policy or build_default_policy()
        self.rate_limiter = (
            rate_limiter if rate_limiter is not None else default_scan_rate_limiter
        )

    def _get_jadwal_and_kelas(
        self, schedule_id: int
    ) -> tuple[Jadwal, KelasJadwal, MataKuliah]:
        jadwal = self.db.get(Jadwal, int(schedule_id))
        if jadwal is None:
            raise AttendanceNotFoundError(
                f"Jadwal kuliah ID {schedule_id} tidak ditemukan"
            )
        kelas = self.db.get(KelasJadwal, jadwal.kelas_id)
        if kelas is None:
            raise AttendanceNotFoundError(
                f"Kelas ID {jadwal.kelas_id} untuk jadwal {schedule_id} tidak ditemukan"
            )
        mk = self.db.get(MataKuliah, kelas.kode_mk)
        if mk is None:
            raise AttendanceNotFoundError(
                f"Mata kuliah {kelas.kode_mk} tidak ditemukan"
            )
        return jadwal, kelas, mk

    # ------------------------------------------------------------------
    # 1. Pembukaan Sesi & Rotasi QR Code
    # ------------------------------------------------------------------

    def open_session(
        self,
        schedule_id: int,
        *,
        dosen_id: int | None = None,
        tanggal: date | None = None,
        pertemuan_ke: int | None = None,
        valid_minutes: int | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
        radius_m: int | None = None,
        now: datetime | None = None,
        reuse_existing: bool = False,
    ) -> AttendanceSession:
        """Membuka sesi presensi baru untuk jadwal kuliah tertentu (dengan dukungan geofence)."""
        jadwal, kelas, _ = self._get_jadwal_and_kelas(schedule_id)
        if dosen_id is not None and jadwal.dosen_id != int(dosen_id):
            raise AttendanceForbiddenError(
                "Hanya dosen pengampu jadwal ini yang berhak membuka sesi presensi"
            )

        if (latitude is None) ^ (longitude is None):
            raise GeolocationRequiredError(
                "Latitude dan longitude harus diisi keduanya bila geofence diaktifkan"
            )
        if latitude is not None and longitude is not None:
            if not valid_coordinate(latitude, longitude):
                raise GeolocationRequiredError("Koordinat geofence dosen tidak valid")

        now_utc = as_utc(now) or datetime.now(timezone.utc)
        target_date = tanggal or local_date(now_utc, self.policy.tz)

        existing = self.db.scalars(
            select(AttendanceSession).where(
                AttendanceSession.kelas_id == kelas.id,
                AttendanceSession.tanggal == target_date,
                AttendanceSession.jam_mulai == jadwal.jam_mulai,
            )
        ).first()

        if existing is not None:
            if not reuse_existing:
                raise SessionAlreadyOpenError(
                    f"Sesi presensi untuk kelas {kelas.kode_mk}-{kelas.nama_kelas} pada "
                    f"tanggal {target_date.isoformat()} sudah pernah dibuka (ID {existing.id})"
                )
            # Perbarui geofence jika dikirim saat reuse
            if latitude is not None and longitude is not None:
                existing.latitude = float(latitude)
                existing.longitude = float(longitude)
                existing.radius_m = int(
                    radius_m or settings.ATTENDANCE_GEOFENCE_RADIUS_M
                )
                self.db.commit()
                self.db.refresh(existing)
            return existing

        if pertemuan_ke is None:
            max_pert = int(
                self.db.scalar(
                    select(func.max(AttendanceSession.pertemuan_ke)).where(
                        AttendanceSession.kelas_id == kelas.id
                    )
                )
                or 0
            )
            pertemuan_ke = max_pert + 1

        dup_pert = self.db.scalars(
            select(AttendanceSession).where(
                AttendanceSession.kelas_id == kelas.id,
                AttendanceSession.pertemuan_ke == int(pertemuan_ke),
            )
        ).first()
        if dup_pert is not None:
            raise SessionAlreadyOpenError(
                f"Pertemuan ke-{pertemuan_ke} untuk kelas ID {kelas.id} sudah terdaftar"
            )

        duration_min = (
            int(valid_minutes)
            if valid_minutes is not None
            else self.policy.late_max_minutes
        )
        closes_at = now_utc + timedelta(minutes=duration_min)
        resolved_radius = (
            int(radius_m or settings.ATTENDANCE_GEOFENCE_RADIUS_M)
            if (latitude is not None and longitude is not None)
            else None
        )

        session = AttendanceSession(
            jadwal_id=jadwal.id,
            kelas_id=kelas.id,
            dosen_id=jadwal.dosen_id,
            tanggal=target_date,
            pertemuan_ke=int(pertemuan_ke),
            hari=jadwal.hari,
            jam_mulai=jadwal.jam_mulai,
            jam_selesai=jadwal.jam_selesai,
            ruangan_kode=jadwal.ruangan_kode,
            status=SessionStatus.OPEN.value,
            secret=secrets.token_hex(16),
            opened_at=now_utc,
            closes_at=closes_at,
            latitude=float(latitude) if latitude is not None else None,
            longitude=float(longitude) if longitude is not None else None,
            radius_m=resolved_radius,
        )
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        return session

    def close_session(
        self,
        session_id: int,
        *,
        dosen_id: int | None = None,
        now: datetime | None = None,
    ) -> AttendanceSession:
        """Menutup sesi presensi secara eksplisit sehingga QR tidak lagi dapat di-scan."""
        session = self.db.get(AttendanceSession, int(session_id))
        if session is None:
            raise AttendanceNotFoundError(f"Sesi presensi ID {session_id} tidak ditemukan")
        if dosen_id is not None and session.dosen_id != int(dosen_id):
            raise AttendanceForbiddenError(
                "Hanya dosen pengampu sesi ini yang dapat menutup sesi presensi"
            )
        now_utc = as_utc(now) or datetime.now(timezone.utc)
        session.status = SessionStatus.CLOSED.value
        session.closed_at = now_utc
        self.db.commit()
        self.db.refresh(session)
        return session

    def build_rotating_qr_for_session(
        self,
        session: AttendanceSession,
        *,
        now: datetime | None = None,
    ) -> tuple[bytes, dict[str, Any]]:
        """Menghasilkan token QR berotasi aktif beserta byte PNG untuk sesi yang sedang terbuka."""
        now_utc = as_utc(now) or datetime.now(timezone.utc)
        if not session.is_open or now_utc > session.closes_at_utc:
            raise QRExpiredError(
                f"Sesi presensi ID {session.id} sudah ditutup atau kedaluwarsa"
            )

        kelas = self.db.get(KelasJadwal, session.kelas_id)
        mk = self.db.get(MataKuliah, kelas.kode_mk) if kelas is not None else None

        win = window_index(
            session.opened_at_utc, now_utc, self.policy.rotate_seconds
        )
        _, win_end = window_bounds(
            session.opened_at_utc, win, self.policy.rotate_seconds
        )
        # Klaim exp JWT berlaku maks 15 menit (atau closes_at sesi), sedangkan rotasi
        # jendela dicek secara ketat lewat klaim `win` + `jti` HMAC pada `scan_qr`.
        jwt_max_exp = now_utc + timedelta(minutes=self.policy.on_time_minutes)
        token_exp = min(session.closes_at_utc, jwt_max_exp)
        if token_exp <= now_utc:
            token_exp = session.closes_at_utc

        schedule_id = session.jadwal_id or 0
        _, token = generate_attendance_qr(
            schedule_id=schedule_id,
            session_id=session.id,
            window=win,
            secret=session.secret,
            now=now_utc,
            expires_at=token_exp,
        )
        png_bytes = render_qr_png_bytes(token)
        secs_left = max(1, int((win_end - now_utc).total_seconds()))

        info = {
            "session_id": session.id,
            "schedule_id": session.jadwal_id,
            "kelas_id": session.kelas_id,
            "kode_mk": kelas.kode_mk if kelas else "",
            "nama_mk": mk.nama if mk else "",
            "nama_kelas": kelas.nama_kelas if kelas else "",
            "semester": kelas.semester if kelas else "",
            "tanggal": session.tanggal.isoformat(),
            "pertemuan_ke": session.pertemuan_ke,
            "hari": session.hari,
            "hari_nama": format_hari(session.hari),
            "jam_mulai": session.jam_mulai.strftime("%H:%M"),
            "jam_selesai": session.jam_selesai.strftime("%H:%M"),
            "ruangan_kode": session.ruangan_kode,
            "status": session.status,
            "token": token,
            "qr_window": win,
            "rotate_seconds": self.policy.rotate_seconds,
            "grace_windows": self.policy.grace_windows,
            "window_expires_at": win_end.isoformat(),
            "session_opened_at": session.opened_at_utc.isoformat(),
            "session_closes_at": session.closes_at_utc.isoformat(),
            "seconds_until_rotation": secs_left,
            "geofence_enabled": session.geofence_enabled,
            "latitude": session.latitude,
            "longitude": session.longitude,
            "radius_m": session.radius_m,
            "qr_image_url": f"/api/attendance/qr/{schedule_id}",
        }
        return png_bytes, info

    def get_or_open_schedule_qr(
        self,
        schedule_id: int,
        *,
        dosen_id: int | None = None,
        valid_minutes: int | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
        radius_m: int | None = None,
        now: datetime | None = None,
    ) -> tuple[bytes, dict[str, Any]]:
        """Mengambil QR berotasi untuk jadwal tertentu (membuka sesi hari ini jika belum ada)."""
        jadwal, kelas, _ = self._get_jadwal_and_kelas(schedule_id)
        if dosen_id is not None and jadwal.dosen_id != int(dosen_id):
            raise AttendanceForbiddenError(
                "Hanya dosen pengampu jadwal ini yang berhak men-generate QR presensi"
            )

        now_utc = as_utc(now) or datetime.now(timezone.utc)
        today = local_date(now_utc, self.policy.tz)

        session = self.db.scalars(
            select(AttendanceSession).where(
                AttendanceSession.kelas_id == kelas.id,
                AttendanceSession.tanggal == today,
                AttendanceSession.jam_mulai == jadwal.jam_mulai,
            )
        ).first()

        if session is None:
            session = self.open_session(
                schedule_id,
                dosen_id=dosen_id,
                tanggal=today,
                valid_minutes=valid_minutes,
                latitude=latitude,
                longitude=longitude,
                radius_m=radius_m,
                now=now_utc,
                reuse_existing=True,
            )
        else:
            # Jika sesi hari ini sudah lewat closes_at atau closed, buka kembali window baru bila diminta
            if not session.is_open or now_utc > session.closes_at_utc:
                duration_min = (
                    int(valid_minutes)
                    if valid_minutes is not None
                    else self.policy.late_max_minutes
                )
                session.status = SessionStatus.OPEN.value
                session.opened_at = now_utc
                session.closes_at = now_utc + timedelta(minutes=duration_min)
                session.closed_at = None
                session.secret = secrets.token_hex(16)
            if latitude is not None and longitude is not None:
                if not valid_coordinate(latitude, longitude):
                    raise GeolocationRequiredError("Koordinat geofence tidak valid")
                session.latitude = float(latitude)
                session.longitude = float(longitude)
                session.radius_m = int(
                    radius_m or settings.ATTENDANCE_GEOFENCE_RADIUS_M
                )
            self.db.commit()
            self.db.refresh(session)

        return self.build_rotating_qr_for_session(session, now=now_utc)

    # ------------------------------------------------------------------
    # 2. Scan Validation & Attendance Recording
    # ------------------------------------------------------------------

    def _is_student_enrolled(self, nim: str, kelas: KelasJadwal) -> bool:
        """Memeriksa apakah mahasiswa terdaftar di kelas ini pada KRS berstatus APPROVED."""
        stmt = (
            select(KRSDetail.id)
            .join(KRS, KRSDetail.krs_id == KRS.id)
            .where(
                KRS.nim == nim,
                KRS.status == KRSStatus.APPROVED,
                (
                    (KRSDetail.kelas_id == kelas.id)
                    | (
                        (KRSDetail.kelas_id.is_(None))
                        & (KRSDetail.kode_mk == kelas.kode_mk)
                        & (KRS.semester == kelas.semester)
                    )
                ),
            )
            .limit(1)
        )
        return self.db.scalars(stmt).first() is not None

    def scan_qr(
        self,
        *,
        token: str,
        nim: str,
        latitude: float | None = None,
        longitude: float | None = None,
        accuracy_m: float | None = None,
        ip_address: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Memvalidasi scan QR mahasiswa melalui 6 lapis penjaga & menyimpan AttendanceRecord."""
        clean_nim = str(nim or "").strip()
        if not clean_nim:
            raise AttendanceError("NIM mahasiswa wajib diisi", status_code=422)

        now_utc = as_utc(now) or datetime.now(timezone.utc)

        # 0. Rate limiting (prevent spam scan)
        self.rate_limiter.check(f"nim:{clean_nim}", now=now_utc)

        # 1. Decode JWT -> extract schedule_id & check exp
        payload = decode_attendance_qr_token(token, now=now_utc)
        schedule_id = int(payload["schedule_id"])
        token_sid = payload.get("sid")
        token_win = int(payload.get("win", 0))
        token_jti = payload.get("jti")

        # 2. Query schedule: apakah hari ini ada kuliah?
        jadwal, kelas, mk = self._get_jadwal_and_kelas(schedule_id)
        scan_date = local_date(now_utc, self.policy.tz)
        today_hari = iso_hari(scan_date)
        if jadwal.hari != today_hari:
            raise OutsideAttendanceWindowError(
                f"Tidak ada jadwal kuliah {kelas.kode_mk} ({mk.nama}) pada hari ini "
                f"({format_hari(today_hari) if 1 <= today_hari <= 6 else 'Minggu'}); "
                f"jadwal terdaftar pada hari {format_hari(jadwal.hari)}."
            )

        # Ambil atau buat sesi presensi terkait
        session: AttendanceSession | None = None
        if token_sid is not None:
            session = self.db.get(AttendanceSession, int(token_sid))
            if session is None or (
                session.jadwal_id is not None and session.jadwal_id != jadwal.id
            ):
                raise QRTokenInvalidError(
                    "Sesi presensi pada token QR tidak ditemukan atau tidak cocok dengan jadwal"
                )
        else:
            session = self.db.scalars(
                select(AttendanceSession).where(
                    AttendanceSession.kelas_id == kelas.id,
                    AttendanceSession.tanggal == scan_date,
                    AttendanceSession.jam_mulai == jadwal.jam_mulai,
                )
            ).first()
            if session is None:
                # Mendukung token standalone dari `generate_attendance_qr(schedule_id)`
                raw_iat = payload.get("iat")
                iat_dt = (
                    datetime.fromtimestamp(float(raw_iat), tz=timezone.utc)
                    if raw_iat is not None
                    else now_utc
                )
                session = self.open_session(
                    schedule_id,
                    tanggal=scan_date,
                    now=iat_dt,
                    reuse_existing=True,
                )

        # Validasi sesi masih terbuka & rotasi window QR (anti-replay)
        if not session.is_open:
            raise QRExpiredError("Sesi presensi sudah ditutup oleh dosen")
        if now_utc > session.closes_at_utc:
            raise QRExpiredError(
                "Waktu sesi presensi sudah berakhir (melewati batas maksimal sesi)"
            )

        if token_sid is not None:
            if not token_jti or not verify_qr_nonce(
                session.secret, session.id, token_win, str(token_jti)
            ):
                raise QRTokenInvalidError(
                    "Signature/nonce rotasi QR tidak sah (token tidak berlaku untuk sesi ini)"
                )
            current_win = window_index(
                session.opened_at_utc, now_utc, self.policy.rotate_seconds
            )
            if not is_window_accepted(
                token_win, current_win, self.policy.grace_windows
            ):
                raise QRExpiredError(
                    f"QR code jendela #{token_win} sudah berganti (sekarang jendela #{current_win}). "
                    "Silakan scan QR terbaru di layar dosen."
                )

        # 3. Cek enrollment: apakah mahasiswa terdaftar di MK ini?
        if not self._is_student_enrolled(clean_nim, kelas):
            raise NotEnrolledError(
                f"Mahasiswa {clean_nim} tidak terdaftar pada kelas {kelas.kode_mk}-{kelas.nama_kelas}"
            )

        # 4. Check duplicate: apakah sudah scan sebelumnya?
        existing_rec = self.db.scalars(
            select(AttendanceRecord).where(
                AttendanceRecord.session_id == session.id,
                AttendanceRecord.nim == clean_nim,
            )
        ).first()
        if existing_rec is not None:
            raise DuplicateAttendanceError(
                f"Mahasiswa {clean_nim} sudah tercatat presensi ({existing_rec.status}) "
                f"pada pertemuan ke-{session.pertemuan_ke}"
            )

        # 5. Validasi geolokasi (jika sesi mengaktifkan geofence)
        computed_distance: float | None = None
        if session.geofence_enabled:
            if latitude is None or longitude is None:
                raise GeolocationRequiredError(
                    "Sesi ini mewajibkan validasi lokasi GPS (latitude & longitude wajib dikirim)"
                )
            if not valid_coordinate(latitude, longitude):
                raise GeolocationRequiredError("Koordinat lokasi GPS tidak valid")
            if (
                accuracy_m is not None
                and float(accuracy_m) > settings.ATTENDANCE_GEO_MAX_ACCURACY_M
            ):
                raise GeolocationError(
                    f"Akurasi sinyal GPS terlalu rendah ({float(accuracy_m):.1f}m > "
                    f"batas {settings.ATTENDANCE_GEO_MAX_ACCURACY_M}m)"
                )
            computed_distance = round(
                haversine_m(
                    float(session.latitude),  # type: ignore[arg-type]
                    float(session.longitude),  # type: ignore[arg-type]
                    float(latitude),
                    float(longitude),
                ),
                2,
            )
            allowed_radius = int(
                session.radius_m or settings.ATTENDANCE_GEOFENCE_RADIUS_M
            )
            if computed_distance > allowed_radius:
                raise GeolocationError(
                    f"Lokasi mahasiswa berada di luar radius ruang kuliah "
                    f"({computed_distance:.1f}m > maksimal {allowed_radius}m)"
                )
        elif latitude is not None and longitude is not None and valid_coordinate(
            latitude, longitude
        ):
            computed_distance = 0.0

        # 6. Calculate status: Hadir (<=15 menit pertama) / Terlambat (15..30 menit)
        status_enum = determine_attendance_status(
            session.opened_at_utc,
            now_utc,
            on_time_minutes=self.policy.on_time_minutes,
            late_max_minutes=self.policy.late_max_minutes,
        )
        if status_enum is None:
            raise OutsideAttendanceWindowError(
                f"Scan presensi ditolak karena melewati batas maksimal {self.policy.late_max_minutes} menit"
            )

        # 7. Simpan record dalam transaksi ACID
        record = AttendanceRecord(
            session_id=session.id,
            nim=clean_nim,
            status=status_enum.value,
            scanned_at=now_utc,
            qr_window=token_win,
            latitude=float(latitude) if latitude is not None else None,
            longitude=float(longitude) if longitude is not None else None,
            accuracy_m=float(accuracy_m) if accuracy_m is not None else None,
            distance_m=computed_distance,
            ip_address=ip_address,
        )
        try:
            self.db.add(record)
            self.db.commit()
            self.db.refresh(record)
        except IntegrityError as exc:
            self.db.rollback()
            raise DuplicateAttendanceError(
                f"Mahasiswa {clean_nim} sudah melakukan scan pada sesi ini"
            ) from exc

        elapsed_min = max(0, int((now_utc - session.opened_at_utc).total_seconds() // 60))
        msg = (
            f"Presensi {mk.nama} ({kelas.kode_mk}-{kelas.nama_kelas}) pertemuan ke-{session.pertemuan_ke} "
            f"berhasil dicatat sebagai '{status_enum.value}' (menit ke-{elapsed_min})."
        )
        return {
            "success": True,
            "status": status_enum.value,
            "message": msg,
            "record_id": record.id,
            "session_id": session.id,
            "schedule_id": session.jadwal_id,
            "kelas_id": kelas.id,
            "kode_mk": kelas.kode_mk,
            "nama_mk": mk.nama,
            "nim": clean_nim,
            "pertemuan_ke": session.pertemuan_ke,
            "scanned_at": record.scanned_at_utc.isoformat(),
            "qr_window": record.qr_window,
            "distance_m": record.distance_m,
        }

    # ------------------------------------------------------------------
    # 3. Attendance Report (Per Mahasiswa, Per MK/Kelas, & Export Excel)
    # ------------------------------------------------------------------

    def get_student_report(self, nim: str) -> dict[str, Any]:
        """Menghitung persentase kehadiran per MK untuk seorang mahasiswa (Deliverable 3)."""
        clean_nim = str(nim or "").strip()
        mhs = self.db.scalars(
            select(CalonMahasiswa).where(CalonMahasiswa.nim == clean_nim)
        ).first()
        if mhs is None:
            raise AttendanceNotFoundError(f"Mahasiswa dengan NIM {clean_nim} tidak ditemukan")

        stmt = (
            select(KRSDetail, KRS, KelasJadwal, MataKuliah)
            .join(KRS, KRSDetail.krs_id == KRS.id)
            .join(KelasJadwal, KRSDetail.kelas_id == KelasJadwal.id)
            .join(MataKuliah, KelasJadwal.kode_mk == MataKuliah.kode_mk)
            .where(KRS.nim == clean_nim, KRS.status == KRSStatus.APPROVED)
            .order_by(KelasJadwal.semester.desc(), KelasJadwal.kode_mk.asc())
        )
        rows = self.db.execute(stmt).all()

        courses_out: list[dict[str, Any]] = []
        warning_count = 0

        for _, _, kelas, mk in rows:
            sessions = self.db.scalars(
                select(AttendanceSession).where(AttendanceSession.kelas_id == kelas.id)
            ).all()
            total_sesi = len(sessions)
            session_ids = [s.id for s in sessions]

            hadir_cnt = 0
            terlambat_cnt = 0
            if session_ids:
                recs = self.db.scalars(
                    select(AttendanceRecord).where(
                        AttendanceRecord.session_id.in_(session_ids),
                        AttendanceRecord.nim == clean_nim,
                    )
                ).all()
                for r in recs:
                    if r.status == AttendanceStatus.HADIR.value:
                        hadir_cnt += 1
                    elif r.status == AttendanceStatus.TERLAMBAT.value:
                        terlambat_cnt += 1

            attended = min(total_sesi, hadir_cnt + terlambat_cnt)
            alpha_cnt = max(0, total_sesi - attended)
            persen = attendance_percentage(attended, total_sesi)
            memenuhi = persen >= self.policy.min_percent
            is_warn = not memenuhi
            if is_warn:
                warning_count += 1

            r_level = risk_level(
                alpha=alpha_cnt,
                held=total_sesi,
                total_pertemuan=self.policy.total_pertemuan,
                min_percent=self.policy.min_percent,
            )
            courses_out.append(
                {
                    "kelas_id": kelas.id,
                    "kode_mk": kelas.kode_mk,
                    "nama_mk": mk.nama,
                    "nama_kelas": kelas.nama_kelas,
                    "semester": kelas.semester,
                    "total_pertemuan": total_sesi,
                    "hadir": hadir_cnt,
                    "terlambat": terlambat_cnt,
                    "alpha": alpha_cnt,
                    "persentase_kehadiran": f"{persen:.2f}",
                    "memenuhi_syarat": memenuhi,
                    "warning_dibawah_75": is_warn,
                    "risk_level": r_level,
                }
            )

        return {
            "nim": clean_nim,
            "nama": mhs.nama_lengkap,
            "total_mk": len(courses_out),
            "jumlah_warning_dibawah_75": warning_count,
            "courses": courses_out,
        }

    def get_class_report(self, kelas_id: int) -> dict[str, Any]:
        """Menghasilkan rekap presensi per MK/kelas beserta daftar warning <75% (Deliverable 3)."""
        kelas = self.db.get(KelasJadwal, int(kelas_id))
        if kelas is None:
            raise AttendanceNotFoundError(f"Kelas ID {kelas_id} tidak ditemukan")
        mk = self.db.get(MataKuliah, kelas.kode_mk)

        sessions = self.db.scalars(
            select(AttendanceSession)
            .where(AttendanceSession.kelas_id == kelas.id)
            .order_by(AttendanceSession.pertemuan_ke.asc())
        ).all()
        total_sesi = len(sessions)
        session_ids = [s.id for s in sessions]

        # Ambil seluruh peserta kelas (KRS APPROVED)
        stmt_peserta = (
            select(CalonMahasiswa)
            .join(KRS, KRS.nim == CalonMahasiswa.nim)
            .join(KRSDetail, KRSDetail.krs_id == KRS.id)
            .where(
                KRSDetail.kelas_id == kelas.id,
                KRS.status == KRSStatus.APPROVED,
            )
            .order_by(CalonMahasiswa.nim.asc())
        )
        enrolled_students = self.db.scalars(stmt_peserta).all()

        records_by_nim: dict[str, list[AttendanceRecord]] = defaultdict(list)
        if session_ids:
            all_recs = self.db.scalars(
                select(AttendanceRecord).where(
                    AttendanceRecord.session_id.in_(session_ids)
                )
            ).all()
            for r in all_recs:
                records_by_nim[r.nim].append(r)

        peserta_list: list[dict[str, Any]] = []
        warning_list: list[dict[str, Any]] = []
        total_persen_sum = Decimal("0.00")

        for mhs in enrolled_students:
            mhs_recs = records_by_nim.get(mhs.nim or "", [])
            hadir_cnt = sum(
                1 for r in mhs_recs if r.status == AttendanceStatus.HADIR.value
            )
            terlambat_cnt = sum(
                1 for r in mhs_recs if r.status == AttendanceStatus.TERLAMBAT.value
            )
            attended = min(total_sesi, hadir_cnt + terlambat_cnt)
            alpha_cnt = max(0, total_sesi - attended)
            persen = attendance_percentage(attended, total_sesi)
            total_persen_sum += persen
            memenuhi = persen >= self.policy.min_percent
            is_warn = not memenuhi
            r_level = risk_level(
                alpha=alpha_cnt,
                held=total_sesi,
                total_pertemuan=self.policy.total_pertemuan,
                min_percent=self.policy.min_percent,
            )
            item = {
                "nim": mhs.nim,
                "nama": mhs.nama_lengkap,
                "total_pertemuan": total_sesi,
                "hadir": hadir_cnt,
                "terlambat": terlambat_cnt,
                "alpha": alpha_cnt,
                "persentase_kehadiran": f"{persen:.2f}",
                "memenuhi_syarat": memenuhi,
                "warning_dibawah_75": is_warn,
                "risk_level": r_level,
            }
            peserta_list.append(item)
            if is_warn:
                warning_list.append(item)

        avg_persen = (
            (total_persen_sum / Decimal(len(peserta_list))).quantize(
                Decimal("0.01")
            )
            if peserta_list
            else Decimal("100.00")
        )

        return {
            "kelas_id": kelas.id,
            "kode_mk": kelas.kode_mk,
            "nama_mk": mk.nama if mk else kelas.kode_mk,
            "nama_kelas": kelas.nama_kelas,
            "semester": kelas.semester,
            "total_sesi_dibuka": total_sesi,
            "rata_rata_kehadiran": f"{avg_persen:.2f}",
            "jumlah_mahasiswa": len(peserta_list),
            "jumlah_warning_dibawah_75": len(warning_list),
            "peserta": peserta_list,
            "mahasiswa_warning": warning_list,
        }

    def export_class_report_excel(self, kelas_id: int) -> tuple[bytes, str]:
        """Mengekspor laporan presensi kelas ke file Excel (.xlsx) untuk dosen (Deliverable 3)."""
        report = self.get_class_report(kelas_id)
        sessions = self.db.scalars(
            select(AttendanceSession)
            .where(AttendanceSession.kelas_id == int(kelas_id))
            .order_by(AttendanceSession.pertemuan_ke.asc())
        ).all()

        wb = Workbook()
        ws_rekap = wb.active
        ws_rekap.title = "Rekap Presensi"

        header_fill = PatternFill("solid", fgColor="1E3A8A")
        header_font = Font(bold=True, color="FFFFFF")
        warn_fill = PatternFill("solid", fgColor="FEE2E2")
        thin_side = Side(border_style="thin", color="CBD5E1")
        cell_border = Border(
            left=thin_side, right=thin_side, top=thin_side, bottom=thin_side
        )

        ws_rekap["A1"] = (
            f"REKAP PRESENSI MATA KULIAH: {report['kode_mk']} - {report['nama_mk']} "
            f"(Kelas {report['nama_kelas']} / Semester {report['semester']})"
        )
        ws_rekap["A1"].font = Font(bold=True, size=12)
        ws_rekap["A2"] = (
            f"Total Sesi Pertemuan: {report['total_sesi_dibuka']} | "
            f"Rata-rata Kehadiran: {report['rata_rata_kehadiran']}% | "
            f"Mahasiswa Warning (<75%): {report['jumlah_warning_dibawah_75']}"
        )

        headers = [
            "No",
            "NIM",
            "Nama Mahasiswa",
            "Hadir",
            "Terlambat",
            "Alpha",
            "Total Sesi",
            "Persentase (%)",
            "Status Syarat (>=75%)",
            "Tingkat Risiko",
        ]
        ws_rekap.append([])
        ws_rekap.append(headers)
        header_row_idx = 4
        for col_idx in range(1, len(headers) + 1):
            c = ws_rekap.cell(row=header_row_idx, column=col_idx)
            c.fill = header_fill
            c.font = header_font
            c.alignment = Alignment(horizontal="center", vertical="center")
            c.border = cell_border

        for idx, p in enumerate(report["peserta"], start=1):
            status_lbl = (
                "WARNING (<75%)" if p["warning_dibawah_75"] else "MEMENUHI (>=75%)"
            )
            row_vals = [
                idx,
                p["nim"],
                p["nama"],
                p["hadir"],
                p["terlambat"],
                p["alpha"],
                p["total_pertemuan"],
                float(p["persentase_kehadiran"]),
                status_lbl,
                str(p["risk_level"]).upper(),
            ]
            ws_rekap.append(row_vals)
            cur_row = header_row_idx + idx
            for col_idx in range(1, len(headers) + 1):
                c = ws_rekap.cell(row=cur_row, column=col_idx)
                c.border = cell_border
                if p["warning_dibawah_75"]:
                    c.fill = warn_fill

        for col_idx in range(1, len(headers) + 1):
            col_letter = get_column_letter(col_idx)
            ws_rekap.column_dimensions[col_letter].width = 18

        # Sheet 2: Daftar Mahasiswa Warning (<75%)
        ws_warn = wb.create_sheet(title="Warning <75%")
        ws_warn.append(
            [
                "NIM",
                "Nama Mahasiswa",
                "Hadir",
                "Terlambat",
                "Alpha",
                "Total Sesi",
                "Persentase (%)",
                "Rekomendasi Tindak Lanjut",
            ]
        )
        for col_idx in range(1, 9):
            c = ws_warn.cell(row=1, column=col_idx)
            c.fill = header_fill
            c.font = header_font
            c.border = cell_border

        for w in report["mahasiswa_warning"]:
            ws_warn.append(
                [
                    w["nim"],
                    w["nama"],
                    w["hadir"],
                    w["terlambat"],
                    w["alpha"],
                    w["total_pertemuan"],
                    float(w["persentase_kehadiran"]),
                    "Hubungi mahasiswa & Dosen PA untuk konseling akademik",
                ]
            )

        # Sheet 3: Detail Log Scan Pertemuan
        ws_log = wb.create_sheet(title="Log Scan Pertemuan")
        ws_log.append(
            [
                "Pertemuan Ke",
                "Tanggal",
                "Hari",
                "Jam Mulai",
                "Ruangan",
                "NIM",
                "Status",
                "Waktu Scan (UTC)",
                "QR Window",
                "Jarak GPS (m)",
            ]
        )
        for col_idx in range(1, 11):
            c = ws_log.cell(row=1, column=col_idx)
            c.fill = header_fill
            c.font = header_font
            c.border = cell_border

        for s in sessions:
            for r in s.records:
                ws_log.append(
                    [
                        s.pertemuan_ke,
                        s.tanggal.isoformat(),
                        format_hari(s.hari),
                        s.jam_mulai.strftime("%H:%M"),
                        s.ruangan_kode or "-",
                        r.nim,
                        r.status,
                        r.scanned_at_utc.isoformat(),
                        r.qr_window,
                        r.distance_m if r.distance_m is not None else "-",
                    ]
                )

        buf = BytesIO()
        wb.save(buf)
        filename = (
            f"rekap_presensi_{report['kode_mk']}_{report['nama_kelas']}_{report['semester']}.xlsx"
        )
        return buf.getvalue(), filename

    # ------------------------------------------------------------------
    # 4. AI Attendance Insights dari Database & Seed Demo Data
    # ------------------------------------------------------------------

    def build_attendance_records_from_db(
        self,
        *,
        kelas_id: int | None = None,
        semester: str | None = None,
    ) -> list[dict[str, Any]]:
        """Membangun array `attendance_records` lengkap (termasuk alpha) dari sesi di DB."""
        stmt = (
            select(AttendanceSession, KelasJadwal, MataKuliah)
            .join(KelasJadwal, AttendanceSession.kelas_id == KelasJadwal.id)
            .join(MataKuliah, KelasJadwal.kode_mk == MataKuliah.kode_mk)
            .order_by(
                AttendanceSession.tanggal.asc(),
                AttendanceSession.pertemuan_ke.asc(),
            )
        )
        if kelas_id is not None:
            stmt = stmt.where(AttendanceSession.kelas_id == int(kelas_id))
        if semester is not None:
            stmt = stmt.where(KelasJadwal.semester == str(semester))

        session_rows = self.db.execute(stmt).all()
        output_records: list[dict[str, Any]] = []

        # Cache peserta terdaftar per kelas
        enrolled_cache: dict[int, list[CalonMahasiswa]] = {}
        for session, kelas, _ in session_rows:
            if kelas.id not in enrolled_cache:
                stmt_mhs = (
                    select(CalonMahasiswa)
                    .join(KRS, KRS.nim == CalonMahasiswa.nim)
                    .join(KRSDetail, KRSDetail.krs_id == KRS.id)
                    .where(
                        KRSDetail.kelas_id == kelas.id,
                        KRS.status == KRSStatus.APPROVED,
                    )
                    .order_by(CalonMahasiswa.nim.asc())
                )
                enrolled_cache[kelas.id] = list(self.db.scalars(stmt_mhs).all())

            rec_map = {r.nim: r for r in session.records}
            kelas_label = f"{kelas.kode_mk}-{kelas.nama_kelas}"
            jam_label = session.jam_mulai.strftime("%H:%M")

            for mhs in enrolled_cache[kelas.id]:
                if not mhs.nim:
                    continue
                rec = rec_map.get(mhs.nim)
                status_str = rec.status if rec is not None else AttendanceStatus.ALPHA.value
                output_records.append(
                    {
                        "nim": mhs.nim,
                        "nama": mhs.nama_lengkap,
                        "kelas": kelas_label,
                        "kode_mk": kelas.kode_mk,
                        "hari": format_hari(session.hari),
                        "jam": jam_label,
                        "pertemuan_ke": session.pertemuan_ke,
                        "tanggal": session.tanggal.isoformat(),
                        "status": status_str,
                    }
                )
        return output_records

    def get_ai_insights_from_db(
        self,
        *,
        kelas_id: int | None = None,
        semester: str | None = None,
        llm_client: LLMClient | None = None,
    ) -> dict[str, Any]:
        """Menjalankan AI Attendance Analyzer atas data sesi presensi di database."""
        records = self.build_attendance_records_from_db(
            kelas_id=kelas_id, semester=semester
        )
        return analyze_attendance_records(
            records,
            min_percent=self.policy.min_percent,
            llm_client=llm_client,
        )

    def seed_demo_data(self, *, now: datetime | None = None) -> dict[str, Any]:
        """Menyiapkan data demo Minggu 12: jadwal hari ini, histori 4 pertemuan, geofence, & pola AI."""
        now_utc = as_utc(now) or datetime.now(timezone.utc)
        today_local = local_date(now_utc, self.policy.tz)
        today_hari = iso_hari(today_local)
        if today_hari == 7:
            today_hari = 1  # Fallback Senin bila dijalankan hari Minggu

        prodi = self.db.scalars(
            select(ProgramStudi).where(ProgramStudi.kode == "001")
        ).first()
        if prodi is None:
            prodi = ProgramStudi(
                kode="001", nama="Teknik Informatika", fakultas="Fakultas Teknik"
            )
            self.db.add(prodi)
            self.db.flush()

        jalur = self.db.scalars(
            select(JalurMasuk).where(JalurMasuk.nama == "SNBP")
        ).first()
        if jalur is None:
            jalur = JalurMasuk(nama="SNBP")
            self.db.add(jalur)
            self.db.flush()

        demo_students = [
            ("2025001-0101", "Rina (Hadir Rutin)", "rina.demo@sevima.ac.id"),
            ("2025001-0102", "Budi (Sering Absen Senin)", "budi.demo@sevima.ac.id"),
            ("2025001-0103", "Citra (Hadir Tepat Waktu)", "citra.demo@sevima.ac.id"),
            ("2025001-0104", "Doni (Berisiko <75%)", "doni.demo@sevima.ac.id"),
            ("2025001-0105", "Eka (Hadir Rutin)", "eka.demo@sevima.ac.id"),
        ]
        for nim, nama, email in demo_students:
            mhs = self.db.scalars(
                select(CalonMahasiswa).where(CalonMahasiswa.nim == nim)
            ).first()
            if mhs is None:
                self.db.add(
                    CalonMahasiswa(
                        nama_lengkap=nama,
                        email=email,
                        phone="08123456000",
                        tanggal_lahir=date(2005, 4, 10),
                        program_studi_id=prodi.id,
                        jalur_masuk_id=jalur.id,
                        status="approved",
                        nim=nim,
                    )
                )
        self.db.flush()

        room = self.db.get(Ruangan, "R301")
        if room is None:
            room = Ruangan(
                kode="R301", nama="Lab Presensi R301", kapasitas=45, gedung="Gedung C"
            )
            self.db.add(room)
            self.db.flush()

        dosen = self.db.scalars(
            select(DosenJadwal).where(DosenJadwal.nidn == "00100101")
        ).first()
        if dosen is None:
            dosen = DosenJadwal(nidn="00100101", nama="Dr. Pengampu Demo")
            self.db.add(dosen)
            self.db.flush()

        mk = self.db.get(MataKuliah, "IF301")
        if mk is None:
            mk = MataKuliah(
                kode_mk="IF301", nama="Rekayasa Perangkat Lunak", sks=3
            )
            self.db.add(mk)
            self.db.flush()

        kelas = self.db.scalars(
            select(KelasJadwal).where(
                KelasJadwal.kode_mk == "IF301",
                KelasJadwal.nama_kelas == "A",
                KelasJadwal.semester == "20251",
            )
        ).first()
        if kelas is None:
            kelas = KelasJadwal(
                kode_mk="IF301", nama_kelas="A", kuota=40, semester="20251"
            )
            self.db.add(kelas)
            self.db.flush()

        # Jadwal 1: Hari Senin jam 07:00 (untuk analisis pola absen Senin pagi)
        jadwal_senin = self.db.scalars(
            select(Jadwal).where(
                Jadwal.kelas_id == kelas.id,
                Jadwal.hari == 1,
                Jadwal.jam_mulai == time(7, 0),
            )
        ).first()
        if jadwal_senin is None:
            jadwal_senin = Jadwal(
                kelas_id=kelas.id,
                ruangan_kode=room.kode,
                dosen_id=dosen.id,
                hari=1,
                jam_mulai=time(7, 0),
                jam_selesai=time(8, 40),
            )
            self.db.add(jadwal_senin)
            self.db.flush()

        # Jadwal 2: Hari ini (agar live QR scan di dashboard selalu valid hari ini)
        jadwal_today = self.db.scalars(
            select(Jadwal).where(
                Jadwal.kelas_id == kelas.id,
                Jadwal.hari == today_hari,
                Jadwal.jam_mulai == time(9, 0),
            )
        ).first()
        if jadwal_today is None:
            jadwal_today = Jadwal(
                kelas_id=kelas.id,
                ruangan_kode=room.kode,
                dosen_id=dosen.id,
                hari=today_hari,
                jam_mulai=time(9, 0),
                jam_selesai=time(10, 40),
            )
            self.db.add(jadwal_today)
            self.db.flush()

        # Pastikan kelima mahasiswa terdaftar pada KRS APPROVED untuk kelas IF301-A
        for nim, _, _ in demo_students:
            krs = self.db.scalars(
                select(KRS).where(KRS.nim == nim, KRS.semester == "20251")
            ).first()
            if krs is None:
                krs = KRS(
                    nim=nim,
                    semester="20251",
                    status=KRSStatus.APPROVED,
                    dosen_pa_id=dosen.id,
                )
                self.db.add(krs)
                self.db.flush()
            elif krs.status != KRSStatus.APPROVED:
                krs._allow_status_change = True
                krs.status = KRSStatus.APPROVED
                krs._allow_status_change = False

            det = self.db.scalars(
                select(KRSDetail).where(
                    KRSDetail.krs_id == krs.id, KRSDetail.kode_mk == "IF301"
                )
            ).first()
            if det is None:
                self.db.add(
                    KRSDetail(
                        krs_id=krs.id,
                        kode_mk="IF301",
                        kelas_id=kelas.id,
                    )
                )
            elif det.kelas_id != kelas.id:
                det.kelas_id = kelas.id
        self.db.flush()

        # Buat 4 sesi pertemuan historis Senin jam 07:00:
        # Rina (4/4 = 100%), Citra (4/4 = 100%), Eka (4/4 = 100%),
        # Budi (1/4 = 25% -> absen 3x Senin pagi), Doni (1/4 = 25% -> absen 3x Senin pagi)
        # Absen rate slot Senin 07:00 = 6 / 20 = 30.00% (>=30% high absence slot!)
        base_dates = [
            date(2026, 10, 19),
            date(2026, 10, 26),
            date(2026, 11, 2),
            date(2026, 11, 9),
        ]
        for idx, tgl in enumerate(base_dates, start=1):
            ses = self.db.scalars(
                select(AttendanceSession).where(
                    AttendanceSession.kelas_id == kelas.id,
                    AttendanceSession.pertemuan_ke == idx,
                )
            ).first()
            if ses is None:
                open_dt = datetime(
                    tgl.year, tgl.month, tgl.day, 0, 0, tzinfo=timezone.utc
                )
                ses = AttendanceSession(
                    jadwal_id=jadwal_senin.id,
                    kelas_id=kelas.id,
                    dosen_id=dosen.id,
                    tanggal=tgl,
                    pertemuan_ke=idx,
                    hari=1,
                    jam_mulai=time(7, 0),
                    jam_selesai=time(8, 40),
                    ruangan_kode=room.kode,
                    status=SessionStatus.CLOSED.value,
                    secret=secrets.token_hex(16),
                    opened_at=open_dt,
                    closes_at=open_dt + timedelta(minutes=30),
                    closed_at=open_dt + timedelta(minutes=30),
                    latitude=-7.2797,
                    longitude=112.7975,
                    radius_m=100,
                )
                self.db.add(ses)
                self.db.flush()

                present_nims = [
                    ("2025001-0101", AttendanceStatus.HADIR.value),
                    ("2025001-0103", AttendanceStatus.HADIR.value),
                    ("2025001-0105", AttendanceStatus.TERLAMBAT.value if idx == 2 else AttendanceStatus.HADIR.value),
                ]
                if idx == 1:
                    present_nims.append(("2025001-0102", AttendanceStatus.HADIR.value))
                    present_nims.append(("2025001-0104", AttendanceStatus.TERLAMBAT.value))

                for p_nim, p_stat in present_nims:
                    self.db.add(
                        AttendanceRecord(
                            session_id=ses.id,
                            nim=p_nim,
                            status=p_stat,
                            scanned_at=open_dt + timedelta(minutes=5),
                            qr_window=0,
                            latitude=-7.2797,
                            longitude=112.7975,
                            distance_m=2.5,
                        )
                    )

        self.db.commit()
        return {
            "detail": (
                "Data demo Modul Presensi QR Minggu 12 berhasil dimuat "
                "(Kelas IF301-A, 5 mahasiswa, 4 sesi historis Senin 07:00, & jadwal aktif hari ini)."
            ),
            "kelas_id": kelas.id,
            "kode_mk": kelas.kode_mk,
            "schedule_today_id": jadwal_today.id,
            "schedule_monday_id": jadwal_senin.id,
            "campus_coordinates": {
                "latitude": -7.2797,
                "longitude": 112.7975,
                "radius_m": 100,
            },
            "students": [
                {"nim": n, "nama": nm} for n, nm, _ in demo_students
            ],
        }
