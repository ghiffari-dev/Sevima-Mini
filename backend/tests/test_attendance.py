from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from io import BytesIO

from fastapi.testclient import TestClient
from hypothesis import given, settings as h_settings, strategies as st
from openpyxl import load_workbook
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import get_db as get_orm_db
from app.core.security import create_access_token
from app.main import app
from app.models.attendance import (
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
)
from app.models.base import Base
from app.models.calon_mahasiswa import CalonMahasiswa
from app.models.grade import PresensiKurangError, seed_skala_nilai
from app.models.jalur_masuk import JalurMasuk
from app.models.krs import KRS, KRSDetail, KRSStatus, MataKuliah
from app.models.program_studi import ProgramStudi
from app.models.schedule import (
    Dosen as DosenJadwal,
    Jadwal,
    Kelas as KelasJadwal,
    Ruangan,
)
from app.services.attendance_ai_analyzer import analyze_attendance_records
from app.services.attendance_rules import (
    AttendancePolicy,
    attendance_percentage,
    determine_attendance_status,
    haversine_m,
    is_window_accepted,
    qr_nonce,
    risk_level,
    valid_coordinate,
    verify_qr_nonce,
    window_index,
)
from app.services.attendance_service import (
    AttendanceService,
    DatabasePresensiPort,
    ScanRateLimiter,
    decode_attendance_qr_token,
    default_scan_rate_limiter,
    generate_attendance_qr,
)
from app.services.grade_service import GradeService
from app.services.schedule_recommender import FakeLLMClient


def _make_memory_session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_connection, connection_record):
        cur = dbapi_connection.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _seed_attendance_base(db) -> dict[str, object]:
    """Menyiapkan data master prodi, mahasiswa, dosen, kelas, jadwal Senin & Jumat, serta KRS APPROVED."""
    seed_skala_nilai(db)
    prodi = ProgramStudi(
        kode="001", nama="Teknik Informatika", fakultas="Fakultas Teknik"
    )
    jalur = JalurMasuk(nama="SNBP")
    db.add_all([prodi, jalur])
    db.flush()

    mhs_rina = CalonMahasiswa(
        nama_lengkap="Rina Hadir",
        email="rina@sevima.ac.id",
        phone="08111111111",
        tanggal_lahir=date(2005, 1, 10),
        program_studi_id=prodi.id,
        jalur_masuk_id=jalur.id,
        status="approved",
        nim="2025001-0101",
    )
    mhs_budi = CalonMahasiswa(
        nama_lengkap="Budi Telat",
        email="budi@sevima.ac.id",
        phone="08222222222",
        tanggal_lahir=date(2005, 2, 15),
        program_studi_id=prodi.id,
        jalur_masuk_id=jalur.id,
        status="approved",
        nim="2025001-0102",
    )
    mhs_luar = CalonMahasiswa(
        nama_lengkap="Andi Kelas Lain",
        email="andi.luar@sevima.ac.id",
        phone="08333333333",
        tanggal_lahir=date(2005, 3, 20),
        program_studi_id=prodi.id,
        jalur_masuk_id=jalur.id,
        status="approved",
        nim="2025001-0999",
    )
    db.add_all([mhs_rina, mhs_budi, mhs_luar])
    db.flush()

    mk1 = MataKuliah(kode_mk="IF301", nama="Rekayasa Perangkat Lunak", sks=3)
    mk2 = MataKuliah(kode_mk="IF302", nama="Kecerdasan Buatan", sks=3)
    room = Ruangan(kode="R301", nama="Lab R301", kapasitas=40)
    dosen = DosenJadwal(nidn="00100101", nama="Dr. Pengampu Presensi")
    dosen_lain = DosenJadwal(nidn="00100999", nama="Dr. Dosen Lain")
    db.add_all([mk1, mk2, room, dosen, dosen_lain])
    db.flush()

    kls1 = KelasJadwal(kode_mk="IF301", nama_kelas="A", kuota=40, semester="20251")
    kls2 = KelasJadwal(kode_mk="IF302", nama_kelas="B", kuota=40, semester="20251")
    db.add_all([kls1, kls2])
    db.flush()

    # Jadwal Senin (hari=1) jam 08:00-09:40
    jadwal_senin = Jadwal(
        kelas_id=kls1.id,
        ruangan_kode=room.kode,
        dosen_id=dosen.id,
        hari=1,
        jam_mulai=time(8, 0),
        jam_selesai=time(9, 40),
    )
    # Jadwal Selasa (hari=2) untuk kelas lain
    jadwal_selasa = Jadwal(
        kelas_id=kls2.id,
        ruangan_kode=room.kode,
        dosen_id=dosen.id,
        hari=2,
        jam_mulai=time(10, 0),
        jam_selesai=time(11, 40),
    )
    db.add_all([jadwal_senin, jadwal_selasa])
    db.flush()

    # Rina & Budi terdaftar (KRS APPROVED) di IF301-A (kls1)
    for nim in ("2025001-0101", "2025001-0102"):
        krs = KRS(
            nim=nim,
            semester="20251",
            status=KRSStatus.APPROVED,
            dosen_pa_id=dosen.id,
        )
        db.add(krs)
        db.flush()
        db.add(
            KRSDetail(
                krs_id=krs.id,
                kode_mk="IF301",
                kelas_id=kls1.id,
            )
        )

    # Andi terdaftar di IF302-B (kls2), BUKAN di kls1
    krs_luar = KRS(
        nim="2025001-0999",
        semester="20251",
        status=KRSStatus.APPROVED,
        dosen_pa_id=dosen.id,
    )
    db.add(krs_luar)
    db.flush()
    db.add(
        KRSDetail(
            krs_id=krs_luar.id,
            kode_mk="IF302",
            kelas_id=kls2.id,
        )
    )
    db.commit()

    return {
        "kelas_id": kls1.id,
        "kelas_lain_id": kls2.id,
        "schedule_senin_id": jadwal_senin.id,
        "schedule_selasa_id": jadwal_selasa.id,
        "dosen_id": dosen.id,
        "dosen_lain_id": dosen_lain.id,
        "rina_nim": "2025001-0101",
        "budi_nim": "2025001-0102",
        "luar_nim": "2025001-0999",
    }


@pytest.fixture()
def attendance_env():
    """Fixture TestClient + SessionFactory terisolasi untuk pengujian Modul Presensi Minggu 12."""
    default_scan_rate_limiter.reset()
    SessionFactory = _make_memory_session_factory()
    with SessionFactory() as db:
        seeded = _seed_attendance_base(db)

    def override_get_db():
        db = SessionFactory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_orm_db] = override_get_db
    dosen_token = create_access_token(
        {
            "sub": "dosen.pengampu@sevima.ac.id",
            "role": "dosen",
            "dosen_id": seeded["dosen_id"],
            "nidn": "00100101",
        }
    )
    rina_token = create_access_token(
        {
            "sub": "rina@sevima.ac.id",
            "role": "mahasiswa",
            "nim": seeded["rina_nim"],
        }
    )
    try:
        with TestClient(app) as client:
            yield {
                "client": client,
                "session_factory": SessionFactory,
                "dosen_headers": {"Authorization": f"Bearer {dosen_token}"},
                "rina_headers": {"Authorization": f"Bearer {rina_token}"},
                **seeded,
            }
    finally:
        app.dependency_overrides.clear()
        default_scan_rate_limiter.reset()


# =====================================================================
# 1. UNIT & PARAMETERIZED TESTS (Functional Core `attendance_rules.py`)
# =====================================================================


@pytest.mark.parametrize(
    ("elapsed_minutes", "expected_status"),
    [
        (-5, AttendanceStatus.HADIR),
        (0, AttendanceStatus.HADIR),
        (10, AttendanceStatus.HADIR),
        (15, AttendanceStatus.HADIR),
        (16, AttendanceStatus.TERLAMBAT),
        (25, AttendanceStatus.TERLAMBAT),
        (30, AttendanceStatus.TERLAMBAT),
        (31, None),
        (60, None),
    ],
)
def test_determine_attendance_status_boundaries(
    elapsed_minutes: int, expected_status: AttendanceStatus | None
):
    """Status presensi wajib HADIR <=15m, TERLAMBAT 15..30m, dan None setelah >30m."""
    start = datetime(2026, 11, 16, 1, 0, tzinfo=timezone.utc)
    scan_time = start + timedelta(minutes=elapsed_minutes)
    assert (
        determine_attendance_status(
            start, scan_time, on_time_minutes=15, late_max_minutes=30
        )
        == expected_status
    )


def test_qr_nonce_and_rotating_window_acceptance():
    """Nonce HMAC-SHA256 unik per sesi & window serta hanya menerima window aktif + grace."""
    secret = "rahasia-sesi-01"
    n0 = qr_nonce(secret, session_id=10, window=0)
    n1 = qr_nonce(secret, session_id=10, window=1)
    n_other_session = qr_nonce(secret, session_id=11, window=0)

    assert n0 != n1
    assert n0 != n_other_session
    assert verify_qr_nonce(secret, 10, 0, n0) is True
    assert verify_qr_nonce(secret, 10, 1, n0) is False

    # Grace = 1 window: pada current_window=2, window 2 & 1 diterima, window 0 & 3 ditolak
    assert is_window_accepted(token_window=2, current_window=2, grace_windows=1) is True
    assert is_window_accepted(token_window=1, current_window=2, grace_windows=1) is True
    assert is_window_accepted(token_window=0, current_window=2, grace_windows=1) is False
    assert is_window_accepted(token_window=3, current_window=2, grace_windows=1) is False


def test_generate_and_decode_attendance_qr_token():
    """Fungsi `generate_attendance_qr` menghasilkan objek QR image dan JWT valid 15 menit."""
    now = datetime(2026, 11, 16, 1, 0, tzinfo=timezone.utc)
    qr_img, token = generate_attendance_qr(
        schedule_id=42, valid_minutes=15, session_id=7, window=2, secret="sec", now=now
    )
    assert qr_img is not None
    payload = decode_attendance_qr_token(token, now=now + timedelta(minutes=10))
    assert payload["schedule_id"] == 42
    assert payload["sid"] == 7
    assert payload["win"] == 2

    # Setelah >15 menit, token wajib ditolak sebagai QRExpiredError (410)
    with pytest.raises(QRExpiredError):
        decode_attendance_qr_token(token, now=now + timedelta(minutes=16))

    # Token rusak wajib ditolak sebagai QRTokenInvalidError (400)
    with pytest.raises(QRTokenInvalidError):
        decode_attendance_qr_token(token + "corrupt", now=now)


@pytest.mark.parametrize(
    ("attended", "total", "expected_percent", "expected_risk"),
    [
        (0, 0, Decimal("100.00"), "aman"),
        (4, 4, Decimal("100.00"), "aman"),
        (3, 4, Decimal("75.00"), "aman"),
        (2, 4, Decimal("50.00"), "berisiko"),
        (10, 14, Decimal("71.43"), "kritis"),
    ],
)
def test_attendance_percentage_and_risk_level(
    attended: int, total: int, expected_percent: Decimal, expected_risk: str
):
    """Persentase kehadiran Decimal ROUND_HALF_UP dan klasifikasi tingkat risiko."""
    pct = attendance_percentage(attended, total)
    assert pct == expected_percent
    alpha = total - attended
    assert (
        risk_level(
            alpha=alpha,
            held=total,
            total_pertemuan=14,
            min_percent=Decimal("75"),
        )
        == expected_risk
    )


# =====================================================================
# 2. HYPOTHESIS PROPERTY-BASED TESTS (2x200 Examples)
# =====================================================================


@h_settings(max_examples=200, deadline=None)
@given(
    total=st.integers(min_value=1, max_value=40),
    a=st.integers(min_value=0, max_value=40),
    b=st.integers(min_value=0, max_value=40),
)
def test_property_attendance_percentage_bounds_and_monotonicity(
    total: int, a: int, b: int
):
    """Properti 1: Persentase kehadiran selalu berada di [0.00, 100.00] dan monotonik naik."""
    low = min(a, b, total)
    high = min(max(a, b), total)
    p_low = attendance_percentage(low, total)
    p_high = attendance_percentage(high, total)

    assert Decimal("0.00") <= p_low <= p_high <= Decimal("100.00")
    assert p_low.as_tuple().exponent == -2
    assert p_high.as_tuple().exponent == -2
    if low == total:
        assert p_low == Decimal("100.00")
    if low == 0:
        assert p_low == Decimal("0.00")


@h_settings(max_examples=200, deadline=None)
@given(
    lat1=st.floats(min_value=-85.0, max_value=85.0, allow_nan=False, allow_infinity=False),
    lon1=st.floats(min_value=-180.0, max_value=180.0, allow_nan=False, allow_infinity=False),
    lat2=st.floats(min_value=-85.0, max_value=85.0, allow_nan=False, allow_infinity=False),
    lon2=st.floats(min_value=-180.0, max_value=180.0, allow_nan=False, allow_infinity=False),
    cur_win=st.integers(min_value=0, max_value=50),
    tok_win=st.integers(min_value=-5, max_value=55),
    grace=st.integers(min_value=0, max_value=5),
)
def test_property_haversine_and_window_rotation_invariants(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
    cur_win: int,
    tok_win: int,
    grace: int,
):
    """Properti 2: Jarak Haversine non-negatif & simetris; rotasi window sesuai interval grace."""
    assert valid_coordinate(lat1, lon1) is True
    d_self = haversine_m(lat1, lon1, lat1, lon1)
    d_ab = haversine_m(lat1, lon1, lat2, lon2)
    d_ba = haversine_m(lat2, lon2, lat1, lon1)

    assert d_self == pytest.approx(0.0, abs=1e-6)
    assert d_ab >= 0.0
    assert d_ab == pytest.approx(d_ba, rel=1e-9, abs=1e-6)

    expected_accept = 0 <= tok_win <= cur_win and (cur_win - tok_win) <= grace
    assert is_window_accepted(tok_win, cur_win, grace) is expected_accept


# =====================================================================
# 3. INTEGRATION TESTS: ROTATING QR, GEOFENCE, RATE LIMIT, & GRADE PORT
# =====================================================================


def test_rotating_qr_lifecycle_and_scan_validations(attendance_env):
    """Menguji siklus hidup rotasi QR otomatis, status hadir vs terlambat, anti-replay, & kelas lain."""
    SessionFactory = attendance_env["session_factory"]
    schedule_id = attendance_env["schedule_senin_id"]
    rina_nim = attendance_env["rina_nim"]
    budi_nim = attendance_env["budi_nim"]
    luar_nim = attendance_env["luar_nim"]

    # Senin, 16 Nov 2026 pukul 08:00 WIB = 01:00 UTC
    t0 = datetime(2026, 11, 16, 1, 0, tzinfo=timezone.utc)

    with SessionFactory() as db:
        policy = AttendancePolicy(
            rotate_seconds=120,
            grace_windows=1,
            on_time_minutes=15,
            late_max_minutes=30,
        )
        svc = AttendanceService(db, policy=policy)

        # Dosen membuka sesi di t0 (Window #0: 0..120s)
        _, info_w0 = svc.get_or_open_schedule_qr(schedule_id, now=t0)
        assert info_w0["qr_window"] == 0
        token_w0 = info_w0["token"]

        # 1. Rina scan di menit ke-5 (Masih Window #2, tapi coba scan token_w0 di menit ke-5 -> lewat grace!)
        # Pada t0 + 5 menit (300s), current_window = 2, sehingga token_w0 (window 0) wajib ditolak!
        with pytest.raises(QRExpiredError, match="berganti"):
            svc.scan_qr(token=token_w0, nim=rina_nim, now=t0 + timedelta(minutes=5))

        # 2. Ambil QR terbaru di menit ke-5 (Window #2) -> Rina berhasil scan ('hadir')
        _, info_w2 = svc.get_or_open_schedule_qr(
            schedule_id, now=t0 + timedelta(minutes=5)
        )
        assert info_w2["qr_window"] == 2
        res_rina = svc.scan_qr(
            token=info_w2["token"],
            nim=rina_nim,
            now=t0 + timedelta(minutes=5, seconds=30),
        )
        assert res_rina["success"] is True
        assert res_rina["status"] == "hadir"

        # 3. Scan ganda oleh Rina pada sesi yang sama wajib ditolak (409 DuplicateAttendanceError)
        with pytest.raises(DuplicateAttendanceError):
            svc.scan_qr(
                token=info_w2["token"],
                nim=rina_nim,
                now=t0 + timedelta(minutes=6),
            )

        # 4. Mahasiswa kelas lain (Andi) tidak bisa scan QR kelas ini (403 NotEnrolledError)
        with pytest.raises(NotEnrolledError):
            svc.scan_qr(
                token=info_w2["token"],
                nim=luar_nim,
                now=t0 + timedelta(minutes=6),
            )

        # 5. Budi scan di menit ke-20 (Window #10) -> tercatat sebagai 'terlambat'
        t_late = t0 + timedelta(minutes=20)
        _, info_w10 = svc.get_or_open_schedule_qr(schedule_id, now=t_late)
        res_budi = svc.scan_qr(
            token=info_w10["token"],
            nim=budi_nim,
            now=t_late + timedelta(seconds=20),
        )
        assert res_budi["status"] == "terlambat"

        # 6. Scan pada hari yang salah (mis. Selasa) wajib ditolak (422 OutsideAttendanceWindowError)
        t_tuesday = datetime(2026, 11, 17, 1, 5, tzinfo=timezone.utc)
        _, raw_tok_tue = generate_attendance_qr(schedule_id, valid_minutes=15, now=t_tuesday)
        with pytest.raises(OutsideAttendanceWindowError, match="Tidak ada jadwal"):
            svc.scan_qr(token=raw_tok_tue, nim=rina_nim, now=t_tuesday)


def test_geolocation_validation_haversine_and_accuracy(attendance_env):
    """Validasi lokasi GPS menolak mahasiswa tanpa koordinat, akurasi buruk, atau di luar radius."""
    SessionFactory = attendance_env["session_factory"]
    schedule_id = attendance_env["schedule_senin_id"]
    rina_nim = attendance_env["rina_nim"]
    t0 = datetime(2026, 11, 16, 1, 0, tzinfo=timezone.utc)

    # Titik pusat kelas: (-7.2797, 112.7975), radius 100m
    room_lat, room_lon = -7.2797, 112.7975

    with SessionFactory() as db:
        svc = AttendanceService(db)
        _, info = svc.get_or_open_schedule_qr(
            schedule_id,
            latitude=room_lat,
            longitude=room_lon,
            radius_m=100,
            now=t0,
        )
        token = info["token"]
        assert info["geofence_enabled"] is True

        # 1. Tanpa koordinat GPS -> 422 GeolocationRequiredError
        with pytest.raises(GeolocationRequiredError):
            svc.scan_qr(token=token, nim=rina_nim, now=t0 + timedelta(seconds=10))

        # 2. Akurasi GPS terlalu buruk (300m > 150m) -> 403 GeolocationError
        with pytest.raises(GeolocationError, match="Akurasi"):
            svc.scan_qr(
                token=token,
                nim=rina_nim,
                latitude=room_lat,
                longitude=room_lon,
                accuracy_m=300.0,
                now=t0 + timedelta(seconds=15),
            )

        # 3. Lokasi di luar radius (~1.5 km dari kelas) -> 403 GeolocationError
        with pytest.raises(GeolocationError, match="di luar radius"):
            svc.scan_qr(
                token=token,
                nim=rina_nim,
                latitude=-7.2920,
                longitude=112.8050,
                accuracy_m=15.0,
                now=t0 + timedelta(seconds=20),
            )

        # 4. Lokasi di dalam ruang kuliah (~11 meter dari titik dosen) -> 200 OK
        res = svc.scan_qr(
            token=token,
            nim=rina_nim,
            latitude=-7.2798,
            longitude=112.7975,
            accuracy_m=10.0,
            now=t0 + timedelta(seconds=25),
        )
        assert res["success"] is True
        assert res["distance_m"] is not None and res["distance_m"] <= 100.0


def test_rate_limiting_prevents_spam_scan(attendance_env):
    """Rate limiter menolak spam scan melebihi batas kuota per menit dengan HTTP 429."""
    SessionFactory = attendance_env["session_factory"]
    schedule_id = attendance_env["schedule_senin_id"]
    rina_nim = attendance_env["rina_nim"]
    t0 = datetime(2026, 11, 16, 1, 0, tzinfo=timezone.utc)

    limiter = ScanRateLimiter(max_requests=3, window_seconds=60)
    with SessionFactory() as db:
        svc = AttendanceService(db, rate_limiter=limiter)
        for i in range(3):
            with pytest.raises(QRTokenInvalidError):
                svc.scan_qr(
                    token="token.palsu.tidakvalid",
                    nim=rina_nim,
                    now=t0 + timedelta(seconds=i * 5),
                )

        # Percobaan ke-4 dalam 60 detik langsung diblokir oleh RateLimitExceededError (429)
        with pytest.raises(RateLimitExceededError) as exc_info:
            svc.scan_qr(
                token="token.palsu.tidakvalid",
                nim=rina_nim,
                now=t0 + timedelta(seconds=20),
            )
        assert exc_info.value.status_code == 429
        assert "Retry-After" in exc_info.value.headers
        assert schedule_id > 0


def test_database_presensi_port_integrates_with_grade_service(attendance_env):
    """DatabasePresensiPort menghubungkan data presensi nyata Minggu 12 ke GradeService Minggu 9."""
    SessionFactory = attendance_env["session_factory"]
    schedule_id = attendance_env["schedule_senin_id"]
    kelas_id = attendance_env["kelas_id"]
    dosen_id = attendance_env["dosen_id"]
    rina_nim = attendance_env["rina_nim"]
    budi_nim = attendance_env["budi_nim"]

    with SessionFactory() as db:
        att_svc = AttendanceService(db)
        # Buka 4 pertemuan pada 4 hari Senin berurutan:
        # Rina hadir di 3 dari 4 sesi (75.00% -> boleh input nilai)
        # Budi hadir di 2 dari 4 sesi (50.00% -> ditolak PresensiKurangError 422)
        mondays = [
            date(2026, 10, 19),
            date(2026, 10, 26),
            date(2026, 11, 2),
            date(2026, 11, 9),
        ]
        for idx, tgl in enumerate(mondays, start=1):
            t_open = datetime(tgl.year, tgl.month, tgl.day, 1, 0, tzinfo=timezone.utc)
            ses = att_svc.open_session(
                schedule_id,
                dosen_id=dosen_id,
                tanggal=tgl,
                pertemuan_ke=idx,
                now=t_open,
            )
            _, info = att_svc.build_rotating_qr_for_session(ses, now=t_open)
            if idx <= 3:
                att_svc.scan_qr(
                    token=info["token"],
                    nim=rina_nim,
                    now=t_open + timedelta(minutes=2),
                )
            if idx <= 2:
                att_svc.scan_qr(
                    token=info["token"],
                    nim=budi_nim,
                    now=t_open + timedelta(minutes=3),
                )

        port = DatabasePresensiPort(db)
        assert port.persentase(rina_nim, kelas_id) == Decimal("75.00")
        assert port.persentase(budi_nim, kelas_id) == Decimal("50.00")

        grade_svc = GradeService(db=db, presensi=port)
        # Rina (75.00%) berhasil diberi nilai A
        res_rina = grade_svc.input_nilai(
            dosen_id=dosen_id, kelas_id=kelas_id, nim=rina_nim, huruf="A"
        )
        assert res_rina.nilai_baru == "A"
        assert res_rina.presensi_persen == Decimal("75.00")

        # Budi (50.00% < 75%) ditolak dengan PresensiKurangError
        with pytest.raises(PresensiKurangError, match="50.00%"):
            grade_svc.input_nilai(
                dosen_id=dosen_id, kelas_id=kelas_id, nim=budi_nim, huruf="B"
            )


# =====================================================================
# 4. API, EXCEL EXPORT, AI INSIGHTS, & UI TESTS (`TestClient`)
# =====================================================================


def test_api_qr_endpoints_and_student_token_anti_spoofing(attendance_env):
    """Menguji endpoint GET /attendance/qr/{id}, POST /attendance/scan, & proteksi spoofing NIM."""
    client: TestClient = attendance_env["client"]
    rina_headers = attendance_env["rina_headers"]
    budi_nim = attendance_env["budi_nim"]

    # Muat data demo agar terdapat jadwal yang jatuh tepat pada hari ini
    seed_res = client.post("/api/attendance/seed-demo")
    assert seed_res.status_code == 200
    seed_data = seed_res.json()
    today_schedule_id = seed_data["schedule_today_id"]

    # 1. GET /attendance/qr/{schedule_id} mengembalikan PNG valid + header token
    png_res = client.get(f"/attendance/qr/{today_schedule_id}")
    assert png_res.status_code == 200
    assert png_res.headers["content-type"] == "image/png"
    assert png_res.content.startswith(b"\x89PNG\r\n\x1a\n")
    token = png_res.headers["x-attendance-token"]
    assert len(token) > 20

    # 2. Mahasiswa Rina yang sedang login mencoba scan menggunakan NIM Budi -> ditolak 403!
    spoof_res = client.post(
        "/attendance/scan",
        headers=rina_headers,
        json={"token": token, "nim": budi_nim},
    )
    assert spoof_res.status_code == 403

    # 3. Mahasiswa Rina scan tanpa mengirim field `nim` di body (diambil otomatis dari JWT) -> 200 OK
    ok_res = client.post(
        "/api/attendance/scan",
        headers=rina_headers,
        json={"token": token},
    )
    assert ok_res.status_code == 200
    body = ok_res.json()
    assert body["success"] is True
    assert body["nim"] == attendance_env["rina_nim"]
    assert body["status"] in {"hadir", "terlambat"}


def test_api_reports_and_excel_export(attendance_env):
    """Menguji laporan presensi per mahasiswa, per MK (<75% warning), dan ekspor Excel (.xlsx)."""
    client: TestClient = attendance_env["client"]
    seed_res = client.post("/api/attendance/seed-demo")
    assert seed_res.status_code == 200
    kelas_id = seed_res.json()["kelas_id"]

    # 1. Report per mahasiswa (Budi memiliki presensi 25.00% < 75% pada 4 sesi historis)
    st_res = client.get("/api/attendance/reports/student/2025001-0102")
    assert st_res.status_code == 200
    st_data = st_res.json()
    assert st_data["nim"] == "2025001-0102"
    assert st_data["jumlah_warning_dibawah_75"] == 1
    assert st_data["courses"][0]["persentase_kehadiran"] == "25.00"
    assert st_data["courses"][0]["warning_dibawah_75"] is True

    # 2. Report per MK / kelas
    cls_res = client.get(f"/api/attendance/reports/class/{kelas_id}")
    assert cls_res.status_code == 200
    cls_data = cls_res.json()
    assert cls_data["total_sesi_dibuka"] == 4
    assert cls_data["jumlah_mahasiswa"] == 5
    assert cls_data["jumlah_warning_dibawah_75"] == 2
    warn_nims = [w["nim"] for w in cls_data["mahasiswa_warning"]]
    assert "2025001-0102" in warn_nims
    assert "2025001-0104" in warn_nims

    # 3. Export ke Excel (.xlsx) untuk dosen
    xlsx_res = client.get(f"/api/attendance/reports/class/{kelas_id}/export.xlsx")
    assert xlsx_res.status_code == 200
    assert (
        xlsx_res.headers["content-type"]
        == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    wb = load_workbook(BytesIO(xlsx_res.content))
    assert wb.sheetnames == ["Rekap Presensi", "Warning <75%", "Log Scan Pertemuan"]
    ws_warn = wb["Warning <75%"]
    # Baris 1 header + 2 mahasiswa warning (Budi & Doni) = 3 baris
    assert ws_warn.max_row == 3


def test_ai_attendance_analyzer_patterns_and_llm_guardrail(attendance_env):
    """Menguji Step 3 AI Attendance Analyzer (JSON array + DB + FakeLLMClient guardrail)."""
    client: TestClient = attendance_env["client"]

    # 1. Step 3: Analisis input JSON array `attendance_records`
    sample_records = [
        {"nim": "M01", "nama": "Mahasiswa X", "kelas": "Kelas Y", "hari": "Senin", "jam": "07:00", "status": "alpha"},
        {"nim": "M01", "nama": "Mahasiswa X", "kelas": "Kelas Y", "hari": "Senin", "jam": "07:00", "status": "alpha"},
        {"nim": "M01", "nama": "Mahasiswa X", "kelas": "Kelas Y", "hari": "Rabu", "jam": "10:00", "status": "hadir"},
        {"nim": "M02", "nama": "Citra", "kelas": "Kelas Y", "hari": "Senin", "jam": "07:00", "status": "hadir"},
        {"nim": "M02", "nama": "Citra", "kelas": "Kelas Y", "hari": "Senin", "jam": "07:00", "status": "hadir"},
        {"nim": "M03", "nama": "Doni", "kelas": "Kelas Y", "hari": "Senin", "jam": "07:00", "status": "hadir"},
        {"nim": "M04", "nama": "Eka", "kelas": "Kelas Y", "hari": "Senin", "jam": "07:00", "status": "hadir"},
        {"nim": "M05", "nama": "Fajar", "kelas": "Kelas Y", "hari": "Senin", "jam": "07:00", "status": "alpha"},
        {"nim": "M05", "nama": "Fajar", "kelas": "Kelas Y", "hari": "Senin", "jam": "07:00", "status": "alpha"},
        {"nim": "M03", "nama": "Doni", "kelas": "Kelas Y", "hari": "Senin", "jam": "07:00", "status": "hadir"},
        {"nim": "M04", "nama": "Eka", "kelas": "Kelas Y", "hari": "Senin", "jam": "07:00", "status": "hadir"},
    ]
    res = client.post(
        "/api/attendance/ai-insights",
        json={"attendance_records": sample_records},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["jumlah_mahasiswa_berisiko"] == 2
    assert "2 mahasiswa berisiko" in data["early_warning"]

    joined_actions = " | ".join(data["actions"])
    assert "Mahasiswa X sering absent Senin pagi -> hubungi untuk konseling" in joined_actions
    assert "Kelas Y di jam 07:00 absen rate 40% -> pertimbangkan reschedule" in joined_actions

    # 2. Uji pengayaan dengan FakeLLMClient & fallback saat JSON LLM rusak
    fake_ok = FakeLLMClient(
        '{"insights": ["Pola tambahan dari LLM"], "actions": ["Koordinasikan dengan Dosen PA"]}'
    )
    enriched = analyze_attendance_records(sample_records, llm_client=fake_ok)
    assert enriched["ai_source"] == "llm"
    assert "Pola tambahan dari LLM" in enriched["insights"]
    assert "Mahasiswa X sering absent Senin pagi -> hubungi untuk konseling" in enriched["actions"]

    fake_bad = FakeLLMClient("BUKAN JSON VALID")
    fallback = analyze_attendance_records(sample_records, llm_client=fake_bad)
    assert fallback["ai_source"] == "deterministic_fallback"


def test_attendance_dashboard_ui_served(attendance_env):
    """Halaman /dashboard/attendance harus tersaji dengan elemen QR, GPS, Excel, & AI Insights."""
    client: TestClient = attendance_env["client"]
    res = client.get("/dashboard/attendance")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    html = res.text
    assert "MINGGU 12: Dashboard Presensi QR Code" in html
    assert "/api/attendance/scan" in html
    assert "export.xlsx" in html
