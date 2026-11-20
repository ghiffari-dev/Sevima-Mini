from __future__ import annotations

from collections import Counter
from datetime import date, time
import json
import logging

from fastapi.testclient import TestClient
from hypothesis import given, settings as h_settings, strategies as st
import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.database import get_db as get_orm_db
from app.main import app
from app.models.base import Base
from app.models.calon_mahasiswa import CalonMahasiswa
from app.models.jalur_masuk import JalurMasuk
from app.models.krs import (
    KRS,
    KRSDetail,
    KRSError,
    KRSLog,
    KRSStatus,
    MataKuliah,
    Notifikasi,
    TransitionError,
)
from app.models.program_studi import ProgramStudi
from app.models.schedule import (
    Dosen,
    Jadwal,
    Kelas,
    Ruangan,
    ScheduleCapacityError,
    ScheduleConflictError,
)
from app.services import schedule_recommender
from app.services.conflict_detector import (
    Conflict,
    JadwalSlot,
    cek_kapasitas,
    check_room_capacity,
    detect_conflicts_naive,
    detect_conflicts_sweep,
    parse_time_value,
)
from app.services.krs_manager import KRSManager
from app.services.schedule_observer import (
    AdminObserver,
    LecturerObserver,
    NotificationManager,
    ScheduleSubject,
    StudentObserver,
    default_notification_manager,
)
from app.services.schedule_recommender import suggest_alternative_schedules
from app.services.scheduling_service import SchedulingService


def j(
    jid: int,
    hari: int,
    mulai: str,
    selesai: str,
    ruangan: str,
    dosen: int,
) -> JadwalSlot:
    """Helper satu baris untuk membuat JadwalSlot dari teks jam."""
    return JadwalSlot(
        id=jid,
        hari=hari,
        jam_mulai=parse_time_value(mulai),
        jam_selesai=parse_time_value(selesai),
        ruangan_kode=ruangan,
        dosen_id=dosen,
    )


# =====================================================================
# 1. Deteksi Bentrok: Example-Based (5+ Bug AI) & Property-Based Testing
# =====================================================================


@pytest.mark.parametrize(
    "jadwal_kedua,harapan",
    [
        # Kasus 1: Ruangan sama, dosen berbeda, waktu bertumpuk -> room_conflict
        (
            j(2, 1, "08:30", "10:30", "A101", 2),
            {Conflict("room_conflict", (1, 2))},
        ),
        # Kasus 2: Dosen sama di ruangan berbeda, waktu bertumpuk -> lecturer_conflict
        (
            j(2, 1, "09:00", "11:00", "B201", 1),
            {Conflict("lecturer_conflict", (1, 2))},
        ),
        # Kasus 3: Kuliah bersambung tepat 09:40 (half-open) -> tidak bentrok!
        (
            j(2, 1, "09:40", "11:20", "A101", 1),
            set(),
        ),
        # Kasus 4: Beda hari (Rabu = 3) -> tidak bentrok!
        (
            j(2, 3, "08:00", "09:40", "A101", 1),
            set(),
        ),
        # Kasus 5: Di dalam jadwal pertama dengan ruang & dosen sama -> 2 konflik sekaligus
        (
            j(2, 1, "08:15", "09:15", "A101", 1),
            {
                Conflict("room_conflict", (1, 2)),
                Conflict("lecturer_conflict", (1, 2)),
            },
        ),
        # Kasus 6: Jam sama persis tapi ruang & dosen beda -> bukan konflik (no time_overlap)
        (
            j(2, 1, "08:00", "09:40", "B201", 2),
            set(),
        ),
        # Kasus 7: Jam tanpa nol di depan ("9:00" < "10:00" sebagai time, bukan string)
        (
            j(2, 1, "9:00", "10:00", "A101", 2),
            {Conflict("room_conflict", (1, 2))},
        ),
    ],
)
def test_deteksi_bentrok_kasus_bug_ai(
    jadwal_kedua: JadwalSlot, harapan: set[Conflict]
) -> None:
    """Mengunci seluruh 5 bug klasik AI pada versi Naive maupun Sort & Sweep."""
    jadwal_pertama = j(1, 1, "08:00", "09:40", "A101", 1)
    assert set(detect_conflicts_naive([jadwal_pertama, jadwal_kedua])) == harapan
    assert set(detect_conflicts_sweep([jadwal_pertama, jadwal_kedua])) == harapan


_jadwal_strategy = st.tuples(
    st.integers(1, 3),                    # hari: Senin-Rabu
    st.integers(7, 16),                   # jam mulai: 07..16
    st.integers(1, 3),                    # durasi: 1..3 jam
    st.sampled_from(["A101", "B201"]),    # 2 ruangan (ruang sempit agar sering bentrok)
    st.integers(1, 3),                    # 3 dosen
)


@h_settings(max_examples=300)
@given(st.lists(_jadwal_strategy, max_size=20))
def test_properti_jadwal_diterima_tidak_pernah_bentrok(
    kandidat: list[tuple[int, int, int, str, int]],
) -> None:
    """Properti 1: Simulasi penerimaan jadwal bertahap tidak pernah menyisakan slot bentrok."""
    diterima: list[JadwalSlot] = []
    for idx, (hari, mulai, durasi, ruang, dosen) in enumerate(kandidat, start=1):
        slot_baru = JadwalSlot(
            id=idx,
            hari=hari,
            jam_mulai=time(mulai, 0),
            jam_selesai=time(mulai + durasi, 0),
            ruangan_kode=ruang,
            dosen_id=dosen,
        )
        if not detect_conflicts_sweep([*diterima, slot_baru]):
            diterima.append(slot_baru)

    # Pemeriksa independen: pecah jadwal diterima menjadi slot 1 jam per ruangan & dosen
    room_slots = Counter(
        (s.hari, h, s.ruangan_kode)
        for s in diterima
        for h in range(s.jam_mulai.hour, s.jam_selesai.hour)
    )
    lecturer_slots = Counter(
        (s.hari, h, s.dosen_id)
        for s in diterima
        for h in range(s.jam_mulai.hour, s.jam_selesai.hour)
    )
    assert max(room_slots.values(), default=0) <= 1
    assert max(lecturer_slots.values(), default=0) <= 1


@h_settings(max_examples=300)
@given(st.lists(_jadwal_strategy, max_size=25))
def test_properti_differential_sweep_sama_dengan_naive(
    kandidat: list[tuple[int, int, int, str, int]],
) -> None:
    """Properti 2 (Differential Testing): Sort & Sweep persis sama isi & jumlahnya dengan Naive."""
    daftar = [
        JadwalSlot(
            id=idx,
            hari=hari,
            jam_mulai=time(mulai, 0),
            jam_selesai=time(mulai + durasi, 0),
            ruangan_kode=ruang,
            dosen_id=dosen,
        )
        for idx, (hari, mulai, durasi, ruang, dosen) in enumerate(kandidat, start=1)
    ]
    assert Counter(detect_conflicts_sweep(daftar)) == Counter(
        detect_conflicts_naive(daftar)
    )


# =====================================================================
# 2. Model Domain, Indeks Gabungan, Capacity Check, & Locking Pesimis
# =====================================================================


def test_empat_model_domain_dan_indeks_gabungan(db_session_and_client) -> None:
    """Memastikan 4 model (Ruangan, Dosen, Kelas, Jadwal), NIDN unik, multi-pertemuan, & indeks gabungan."""
    index_names = {idx.name for idx in Jadwal.__table__.indexes}
    assert "ix_jadwal_hari_ruangan" in index_names
    assert "ix_jadwal_hari_dosen" in index_names

    TestingSessionLocal, _ = db_session_and_client
    with TestingSessionLocal() as db:
        # NIDN unik ditolak oleh DB constraint (0010018001 sudah ada di fixture)
        db.add(Dosen(nidn="0010018001", nama="Dosen Duplikat"))
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()

        # Satu kelas paralel bisa punya >1 pertemuan per minggu (Senin teori, Kamis lab)
        kls_b = Kelas(kode_mk="IF201", nama_kelas="B", kuota=30, semester="20251")
        db.add(kls_b)
        db.flush()

        dosen = db.scalars(select(Dosen)).first()
        assert dosen is not None
        db.add_all(
            [
                Jadwal(
                    kelas_id=kls_b.id,
                    ruangan_kode="A101",
                    dosen_id=dosen.id,
                    hari=1,
                    jam_mulai=time(8, 0),
                    jam_selesai=time(10, 0),
                ),
                Jadwal(
                    kelas_id=kls_b.id,
                    ruangan_kode="A102",
                    dosen_id=dosen.id,
                    hari=4,
                    jam_mulai=time(13, 0),
                    jam_selesai=time(15, 0),
                ),
            ]
        )
        db.commit()
        db.refresh(kls_b)
        assert len(kls_b.jadwals) == 2


def test_capacity_check_max_kuota_dan_terdaftar_status_409(db_session_and_client) -> None:
    """Kapasitas memakai <= dan max(kuota, terdaftar), melempar 409 Conflict beserta detail ruang."""
    check_room_capacity(40, 40, "A101")
    with pytest.raises(ScheduleCapacityError) as exc_stateless:
        check_room_capacity(41, 40, "A101")
    assert exc_stateless.value.status_code == 409

    TestingSessionLocal, _ = db_session_and_client
    with TestingSessionLocal() as db:
        ruang_40 = db.get(Ruangan, "A101")
        assert ruang_40 is not None and ruang_40.kapasitas == 40

        # Kelas kuota 50 meski terdaftar masih 0 harus ditolak di ruang kapasitas 40
        kls_50 = Kelas(kode_mk="MA101", nama_kelas="B", kuota=50, semester="20251")
        db.add(kls_50)
        db.flush()

        with pytest.raises(ScheduleCapacityError) as exc_info:
            cek_kapasitas(db, ruang_40, kls_50)
        assert exc_info.value.status_code == 409
        msg = str(exc_info.value)
        assert "A101" in msg and "40" in msg and "50" in msg


def test_pessimistic_lock_order_and_update_exclude_self(
    db_session_and_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Memastikan _kunci memanggil with_for_update() berurutan (Ruangan lalu Dosen) & update mengecualikan diri."""
    from sqlalchemy.dialects import mysql
    from sqlalchemy.sql.selectable import Select

    TestingSessionLocal, _ = db_session_and_client
    with TestingSessionLocal() as db:
        svc = SchedulingService(db)
        kls = db.scalars(select(Kelas).where(Kelas.kode_mk == "MA101")).first()
        dosen = db.scalars(select(Dosen)).first()
        assert kls is not None and dosen is not None

        created = svc.create_schedule(
            kelas_id=kls.id,
            ruangan_kode="A101",
            dosen_id=dosen.id,
            hari=1,
            jam_mulai="08:00",
            jam_selesai="09:40",
        )
        sched_id = created["schedule"]["id"]

        # Tangkap panggilan with_for_update() dan SQL yang dieksekusi selama update_schedule
        locked_statements_mysql: list[str] = []
        orig_with_for_update = Select.with_for_update

        def _spy_for_update(self, **kwargs):
            stmt = orig_with_for_update(self, **kwargs)
            locked_statements_mysql.append(
                str(stmt.compile(dialect=mysql.dialect())).lower()
            )
            return stmt

        monkeypatch.setattr(Select, "with_for_update", _spy_for_update)

        captured_sql: list[str] = []

        def _capture_sql(conn, cursor, statement, parameters, context, executemany):
            captured_sql.append(statement.lower())

        event.listen(db.get_bind(), "before_cursor_execute", _capture_sql)
        try:
            # Geser 15 menit (08:00-09:40 -> 08:15-09:55) tidak boleh bentrok dengan dirinya sendiri
            updated = svc.update_schedule(
                sched_id,
                jam_mulai="08:15",
                jam_selesai="09:55",
            )
            assert updated["schedule"]["jam"] == "08:15-09:55"
        finally:
            event.remove(db.get_bind(), "before_cursor_execute", _capture_sql)

        # Pastikan FOR UPDATE dipanggil berurutan: Ruangan dulu, lalu Dosen (untuk MySQL/PostgreSQL)
        room_lock_idx = next(
            (i for i, s in enumerate(locked_statements_mysql) if "from ruangan" in s and "for update" in s),
            -1,
        )
        dosen_lock_idx = next(
            (i for i, s in enumerate(locked_statements_mysql) if "from dosen" in s and "for update" in s),
            -1,
        )
        assert 0 <= room_lock_idx < dosen_lock_idx

        # Pastikan urutan eksekusi query ke DB pada _simpan(): kunci ruangan -> kunci dosen -> cek bentrok jadwal
        exec_room = next(
            (i for i, s in enumerate(captured_sql) if "from ruangan" in s and "where ruangan.kode" in s),
            -1,
        )
        exec_dosen = next(
            (i for i, s in enumerate(captured_sql) if i > exec_room and "from dosen" in s and "where dosen.id" in s),
            -1,
        )
        exec_conflict = next(
            (i for i, s in enumerate(captured_sql) if i > exec_dosen and "select jadwal.id" in s),
            -1,
        )
        assert 0 <= exec_room < exec_dosen < exec_conflict


# =====================================================================
# 3. Observer Pattern Notification Tests (Minggu 8)
# =====================================================================


def test_observer_pattern_attach_detach_and_simulated_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="schedule.notifications")
    subject = ScheduleSubject()
    student_obs = StudentObserver()
    lecturer_obs = LecturerObserver()
    admin_obs = AdminObserver()

    subject.attach(student_obs)
    subject.attach(student_obs)  # idempoten
    subject.attach(lecturer_obs)
    subject.attach(admin_obs)
    assert len(subject.observers) == 3

    records = subject.notify(
        "SCHEDULE_CHANGED",
        {
            "kode_mk": "MA101",
            "nama_mk": "Kalkulus I",
            "hari": "Selasa",
            "jam": "08:00-10:00",
            "ruangan": "A102",
            "dosen": "Dr. Budi",
            "affected_nims": ["2025001-0001"],
            "invalidated_krs_ids": [1],
        },
    )

    observers_hit = {r.observer for r in records}
    media_hit = {r.medium for r in records}
    assert observers_hit == {"StudentObserver", "LecturerObserver", "AdminObserver"}
    assert media_hit == {"EMAIL", "SMS", "PUSH"}

    log_text = caplog.text
    assert "[SIMULATED EMAIL]" in log_text
    assert "[SIMULATED SMS]" in log_text
    assert "[SIMULATED PUSH]" in log_text
    assert "Kalkulus I" in log_text

    subject.detach(admin_obs)
    assert len(subject.observers) == 2
    records_after = subject.notify(
        "SCHEDULE_CHANGED",
        {
            "kode_mk": "MA101",
            "nama_mk": "Kalkulus I",
            "hari": "Rabu",
            "jam": "08:00-10:00",
            "ruangan": "A102",
            "dosen": "Dr. Budi",
        },
    )
    assert "AdminObserver" not in {r.observer for r in records_after}

    mgr = NotificationManager()
    mgr.notify(
        "SCHEDULE_CHANGED",
        {"kode_mk": "IF201", "nama_mk": "Basis Data", "dosen": "Dr. Siti"},
    )
    assert len(mgr.get_logs()) > 0
    mgr.clear_logs()
    assert mgr.get_logs() == []


# =====================================================================
# 4. Hybrid AI-Powered Rescheduler Tests (Minggu 8)
# =====================================================================


def test_ai_rescheduler_fallback_respects_constraints_pdf_scenario() -> None:
    conflicted = {
        "id": 1,
        "kode_mk": "MA101",
        "nama_mk": "Kalkulus I",
        "hari": "Senin",
        "jam_mulai": "08:00",
        "jam_selesai": "10:00",
        "ruangan": "A101",
        "dosen": "Dr. Budi",
        "enrolled_count": 40,
    }
    existing = [
        conflicted,
        {
            "id": 2,
            "kode_mk": "IF201",
            "nama_mk": "Basis Data",
            "hari": "Senin",
            "jam_mulai": "08:30",
            "jam_selesai": "10:30",
            "ruangan": "A101",
            "dosen": "Dr. Siti",
            "enrolled_count": 30,
        },
        {
            "id": 3,
            "kode_mk": "IF202",
            "nama_mk": "PBO",
            "hari": "Senin",
            "jam_mulai": "13:00",
            "jam_selesai": "15:00",
            "ruangan": "A102",
            "dosen": "Dr. Budi",
            "enrolled_count": 35,
        },
    ]
    rooms = [
        {"kode": "Lab-Kecil", "kapasitas": 25},  # terlalu kecil (< 40)
        {"kode": "A101", "kapasitas": 40},
        {"kode": "A102", "kapasitas": 45},
    ]

    res = suggest_alternative_schedules(
        conflicted, existing, rooms, top_k=3, use_ai=False
    )
    assert res["source"] == "rule_based_fallback"
    assert len(res["recommendations"]) == 3
    for rec in res["recommendations"]:
        assert {"hari", "jam", "ruangan", "reason"}.issubset(rec.keys())
        assert rec["ruangan"] != "Lab-Kecil"
        assert rec["kapasitas"] >= 40
        # Tidak boleh bentrok dengan Dr. Budi di Senin 13:00-15:00
        assert not (rec["hari"] == "Senin" and rec["jam"] == "13:00-15:00")


def test_ai_rescheduler_hybrid_guardrail_rejects_hallucinated_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conflicted = {
        "id": 1,
        "kode_mk": "MA101",
        "nama_mk": "Kalkulus I",
        "hari": "Senin",
        "jam_mulai": "08:00",
        "jam_selesai": "10:00",
        "ruangan": "A101",
        "dosen": "Dr. Budi",
        "enrolled_count": 40,
    }
    existing = [
        conflicted,
        {
            "id": 2,
            "kode_mk": "IF201",
            "nama_mk": "Basis Data",
            "hari": "Selasa",
            "jam_mulai": "08:00",
            "jam_selesai": "10:00",
            "ruangan": "A102",
            "dosen": "Dr. Siti",
            "enrolled_count": 30,
        },
    ]
    rooms = [
        {"kode": "Lab-Kecil", "kapasitas": 20},
        {"kode": "A102", "kapasitas": 45},
        {"kode": "A201", "kapasitas": 50},
    ]

    fake_ai_payload = json.dumps(
        [
            {"hari": "Rabu", "jam": "08:00-10:00", "ruangan": "Lab-Kecil", "reason": "Kecil"},
            {"hari": "Selasa", "jam": "08:00-10:00", "ruangan": "A102", "reason": "Bentrok"},
            {"hari": "Rabu", "jam": "08:00-10:00", "ruangan": "A102", "reason": "AI valid slot"},
        ]
    )
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "dummy-key")
    monkeypatch.setattr(schedule_recommender, "_call_llm_raw", lambda prompt: fake_ai_payload)

    res = suggest_alternative_schedules(
        conflicted, existing, rooms, top_k=3, use_ai=True
    )
    assert res["source"] == "ai_with_fallback"
    assert len(res["recommendations"]) == 3
    first = res["recommendations"][0]
    assert first["hari"] == "Rabu"
    assert first["ruangan"] == "A102"
    assert first["reason"] == "AI valid slot"
    assert all(r["ruangan"] != "Lab-Kecil" for r in res["recommendations"])


# =====================================================================
# 5. KRS Integration & API / UI Tests
# =====================================================================


@pytest.fixture()
def db_session_and_client():
    """Menyediakan DB SQLite in-memory terisolasi + TestClient FastAPI."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    with TestingSessionLocal() as db:
        prodi = ProgramStudi(kode="001", nama="Teknik Informatika", fakultas="Teknik")
        jalur = JalurMasuk(nama="SNBP")
        db.add_all([prodi, jalur])
        db.flush()

        m1 = CalonMahasiswa(
            nama_lengkap="Rina Wulandari",
            email="rina@example.com",
            phone="081234567890",
            tanggal_lahir=date(2005, 4, 12),
            program_studi_id=prodi.id,
            jalur_masuk_id=jalur.id,
            status="approved",
            nim="2025001-0001",
        )
        m2 = CalonMahasiswa(
            nama_lengkap="Dimas Pratama",
            email="dimas@example.com",
            phone="081234567891",
            tanggal_lahir=date(2005, 6, 15),
            program_studi_id=prodi.id,
            jalur_masuk_id=jalur.id,
            status="approved",
            nim="2025001-0002",
        )
        m3 = CalonMahasiswa(
            nama_lengkap="Sari Melati",
            email="sari@example.com",
            phone="081234567892",
            tanggal_lahir=date(2005, 8, 20),
            program_studi_id=prodi.id,
            jalur_masuk_id=jalur.id,
            status="approved",
            nim="2025001-0003",
        )
        mk1 = MataKuliah(kode_mk="MA101", nama="Kalkulus I", sks=3)
        mk2 = MataKuliah(kode_mk="IF201", nama="Basis Data", sks=3)
        mk3 = MataKuliah(kode_mk="IF203", nama="Jaringan Komputer", sks=3)

        r1 = Ruangan(kode="A101", nama="Ruang A101", kapasitas=40, gedung="A")
        r2 = Ruangan(kode="A102", nama="Ruang A102", kapasitas=45, gedung="A")
        r_small = Ruangan(kode="K01", nama="Ruang Kecil", kapasitas=2, gedung="B")

        d1 = Dosen(nidn="0010018001", nama="Dr. Budi")
        d2 = Dosen(nidn="0015028202", nama="Dr. Siti")

        k1 = Kelas(kode_mk="MA101", nama_kelas="A", kuota=40, semester="20251")
        k2 = Kelas(kode_mk="IF201", nama_kelas="A", kuota=30, semester="20251")
        k3 = Kelas(kode_mk="IF203", nama_kelas="A", kuota=30, semester="20251")

        db.add_all([m1, m2, m3, mk1, mk2, mk3, r1, r2, r_small, d1, d2, k1, k2, k3])
        db.commit()

    def override_get_orm_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    default_notification_manager.clear_logs()
    app.dependency_overrides[get_orm_db] = override_get_orm_db
    try:
        with TestClient(app) as client:
            yield TestingSessionLocal, client
    finally:
        app.dependency_overrides.clear()
        default_notification_manager.clear_logs()


def test_krs_conflict_dengan_multi_pertemuan_dalam_satu_kelas(
    db_session_and_client,
) -> None:
    """Satu kelas bisa bertemu Senin teori & Kamis praktikum; KRS mendeteksi bentrok di pertemuan kedua."""
    TestingSessionLocal, _ = db_session_and_client
    with TestingSessionLocal() as db:
        svc = SchedulingService(db)
        k_ma = db.scalars(select(Kelas).where(Kelas.kode_mk == "MA101")).first()
        k_if = db.scalars(select(Kelas).where(Kelas.kode_mk == "IF201")).first()
        d1 = db.scalars(select(Dosen).where(Dosen.nidn == "0010018001")).first()
        d2 = db.scalars(select(Dosen).where(Dosen.nidn == "0015028202")).first()
        assert k_ma and k_if and d1 and d2

        # MA101 A bertemu Senin 08:00-10:00 (teori) dan Kamis 13:00-15:00 (praktikum)
        svc.create_schedule(
            kelas_id=k_ma.id, ruangan_kode="A101", dosen_id=d1.id, hari=1, jam_mulai="08:00", jam_selesai="10:00"
        )
        svc.create_schedule(
            kelas_id=k_ma.id, ruangan_kode="A102", dosen_id=d1.id, hari=4, jam_mulai="13:00", jam_selesai="15:00"
        )
        # IF201 A bertemu Kamis 14:00-16:00 (bentrok dengan praktikum Kamis MA101)
        svc.create_schedule(
            kelas_id=k_if.id, ruangan_kode="A101", dosen_id=d2.id, hari=4, jam_mulai="14:00", jam_selesai="16:00"
        )

        mgr = KRSManager(db, semester="20251", dosen_pa_id=10)
        det = mgr.add_course("2025001-0001", "MA101", kelas_id=k_ma.id)
        assert det.kelas_id == k_ma.id

        with pytest.raises(KRSError, match="Jadwal bentrok"):
            mgr.add_course("2025001-0001", "IF201", kelas_id=k_if.id)


def test_schedule_update_and_delete_invalidate_affected_krs_to_revision(
    db_session_and_client,
) -> None:
    TestingSessionLocal, _ = db_session_and_client
    notif_mgr = NotificationManager()

    with TestingSessionLocal() as db:
        k_ma = db.scalars(select(Kelas).where(Kelas.kode_mk == "MA101")).first()
        k_jarkom = db.scalars(select(Kelas).where(Kelas.kode_mk == "IF203")).first()
        d1 = db.scalars(select(Dosen).where(Dosen.nidn == "0010018001")).first()
        assert k_ma and k_jarkom and d1

        mgr = KRSManager(db, semester="20251", dosen_pa_id=10)
        mgr.add_course("2025001-0001", "MA101", kelas_id=k_ma.id)
        krs1 = mgr.submit_krs("2025001-0001")
        mgr.approve_krs("2025001-0001", dosen_pa_id=10, version=krs1.version)

        mgr.add_course("2025001-0002", "MA101", kelas_id=k_ma.id)
        mgr.submit_krs("2025001-0002")

        mgr.add_course("2025001-0003", "IF203", kelas_id=k_jarkom.id)
        krs3 = mgr.submit_krs("2025001-0003")
        mgr.approve_krs("2025001-0003", dosen_pa_id=10, version=krs3.version)

        krs_check = db.scalars(select(KRS).where(KRS.nim == "2025001-0001")).first()
        assert krs_check is not None
        with pytest.raises(TransitionError):
            krs_check.status = KRSStatus.REVISION

        sched_svc = SchedulingService(db, notification_manager=notif_mgr)
        created = sched_svc.create_schedule(
            kelas_id=k_ma.id,
            ruangan_kode="A101",
            dosen_id=d1.id,
            hari=1,
            jam_mulai="08:00",
            jam_selesai="10:00",
        )
        sched_id = created["schedule"]["id"]

        upd = sched_svc.update_schedule(
            sched_id,
            ruangan_kode="A102",
            hari=2,
            jam_mulai="10:00",
            jam_selesai="12:00",
        )
        assert set(upd["invalidated_krs_nims"]) == {"2025001-0001", "2025001-0002"}
        assert len(upd["notifications_sent"]) > 0

    with TestingSessionLocal() as db:
        k1 = db.scalars(select(KRS).where(KRS.nim == "2025001-0001")).first()
        k2 = db.scalars(select(KRS).where(KRS.nim == "2025001-0002")).first()
        k3 = db.scalars(select(KRS).where(KRS.nim == "2025001-0003")).first()

        assert k1 is not None and k1.status == KRSStatus.REVISION
        assert k1.approved_at is None
        assert k1.catatan_revisi is not None and "MA101" in k1.catatan_revisi
        assert k2 is not None and k2.status == KRSStatus.REVISION
        assert k3 is not None and k3.status == KRSStatus.APPROVED

        logs = db.scalars(
            select(KRSLog).where(KRSLog.aksi == "invalidate_schedule_change")
        ).all()
        assert len(logs) == 2

        notifs_db = db.scalars(select(Notifikasi)).all()
        assert any(n.nim == "2025001-0001" for n in notifs_db)
        assert any(n.nim == "2025001-0002" for n in notifs_db)

        mgr = KRSManager(db, semester="20251", dosen_pa_id=10)
        resubmitted = mgr.submit_krs("2025001-0001")
        assert resubmitted.status == KRSStatus.SUBMITTED

        sched_svc = SchedulingService(db, notification_manager=notif_mgr)
        deleted = sched_svc.delete_schedule(sched_id)
        assert "2025001-0001" in deleted["invalidated_krs_nims"]
        k1_after = db.scalars(select(KRS).where(KRS.nim == "2025001-0001")).first()
        assert k1_after is not None and k1_after.status == KRSStatus.REVISION


def test_schedule_api_endpoints_404_409_422_and_conflict_resolver_ui(
    db_session_and_client,
) -> None:
    TestingSessionLocal, client = db_session_and_client

    # Master endpoint rooms, lecturers, classes
    room_resp = client.post(
        "/api/schedules/rooms",
        json={"kode": "A201", "nama": "Ruang A201", "kapasitas": 50, "gedung": "A"},
    )
    assert room_resp.status_code == 201
    assert room_resp.json()["kode"] == "A201"

    lec_resp = client.post(
        "/api/schedules/lecturers",
        json={"nidn": "0030039003", "nama": "Dr. Baru"},
    )
    assert lec_resp.status_code == 201

    cls_resp = client.post(
        "/api/schedules/classes",
        json={"kode_mk": "IF201", "nama_kelas": "B", "kuota": 35, "semester": "20251"},
    )
    assert cls_resp.status_code == 201

    with TestingSessionLocal() as db:
        k_ma = db.scalars(select(Kelas).where(Kelas.kode_mk == "MA101", Kelas.nama_kelas == "A")).first()
        k_if = db.scalars(select(Kelas).where(Kelas.kode_mk == "IF201", Kelas.nama_kelas == "A")).first()
        d1 = db.scalars(select(Dosen).where(Dosen.nidn == "0010018001")).first()
        d2 = db.scalars(select(Dosen).where(Dosen.nidn == "0015028202")).first()
        assert k_ma and k_if and d1 and d2
        k_ma_id, k_if_id, d1_id, d2_id = k_ma.id, k_if.id, d1.id, d2.id

    # 1. Validasi Pydantic format jam terbalik -> 422 Unprocessable Entity
    err_422_jam = client.post(
        "/api/schedules",
        json={
            "kelas_id": k_ma_id,
            "ruangan_kode": "A101",
            "dosen_id": d1_id,
            "hari": 1,
            "jam_mulai": "10:00",
            "jam_selesai": "08:00",
        },
    )
    assert err_422_jam.status_code == 422

    # Hari di luar 1..6 -> 422
    err_422_hari = client.post(
        "/api/schedules",
        json={
            "kelas_id": k_ma_id,
            "ruangan_kode": "A101",
            "dosen_id": d1_id,
            "hari": 9,
            "jam_mulai": "08:00",
            "jam_selesai": "10:00",
        },
    )
    assert err_422_hari.status_code == 422

    # 2. ID tidak ditemukan -> 404 Not Found
    assert client.get("/api/schedules/99999").status_code == 404

    # 3. Kapasitas overflow -> 409 Conflict (polimorfisme ScheduleCapacityError)
    cap_err = client.post(
        "/api/schedules",
        json={
            "kelas_id": k_ma_id,  # kuota 40 vs ruang K01 kapasitas 2
            "ruangan_kode": "K01",
            "dosen_id": d1_id,
            "hari": 1,
            "jam_mulai": "08:00",
            "jam_selesai": "10:00",
        },
    )
    assert cap_err.status_code == 409
    assert "K01" in cap_err.json()["detail"]

    # 4. Buat jadwal pertama (Senin 08:00-10:00 A101)
    s1 = client.post(
        "/api/schedules",
        json={
            "kelas_id": k_ma_id,
            "ruangan_kode": "A101",
            "dosen_id": d1_id,
            "hari": "Senin",
            "jam_mulai": "08:00",
            "jam_selesai": "10:00",
        },
    )
    assert s1.status_code == 201
    s1_id = s1.json()["schedule"]["id"]

    # 5. Jadwal bentrok ditolak 409 dengan body() berisi conflicts[].type == "room_conflict"
    s2_conflict = client.post(
        "/api/schedules",
        json={
            "kelas_id": k_if_id,
            "ruangan_kode": "A101",
            "dosen_id": d2_id,
            "hari": "Senin",
            "jam_mulai": "08:30",
            "jam_selesai": "10:30",
            "force": False,
        },
    )
    assert s2_conflict.status_code == 409
    body_409 = s2_conflict.json()
    assert body_409["conflicts"][0]["type"] == "room_conflict"
    assert s1_id in body_409["conflicts"][0]["affected"]

    # Dengan force=True -> tersimpan untuk simulasi resolver UI
    s2_forced = client.post(
        "/api/schedules",
        json={
            "kelas_id": k_if_id,
            "ruangan_kode": "A101",
            "dosen_id": d2_id,
            "hari": "Senin",
            "jam_mulai": "08:30",
            "jam_selesai": "10:30",
            "force": True,
        },
    )
    assert s2_forced.status_code == 201

    # 6. GET /api/schedules/conflicts
    conflicts_resp = client.get("/api/schedules/conflicts")
    assert conflicts_resp.status_code == 200
    assert conflicts_resp.json()["total_conflicts"] >= 1
    assert conflicts_resp.json()["conflicts"][0]["type"] == "room_conflict"

    # 7. Saran alternatif AI + terapkan via PUT -> bentrok hilang
    suggest_resp = client.post(f"/api/schedules/{s1_id}/suggest-alternatives")
    assert suggest_resp.status_code == 200
    recs = suggest_resp.json()["recommendations"]
    assert len(recs) == 3

    chosen = recs[0]
    put_resp = client.put(
        f"/api/schedules/{s1_id}",
        json={
            "hari": chosen["hari_num"],
            "jam_mulai": chosen["jam_mulai"],
            "jam_selesai": chosen["jam_selesai"],
            "ruangan_kode": chosen["ruangan"],
            "force": False,
        },
    )
    assert put_resp.status_code == 200
    assert client.get("/api/schedules/conflicts").json()["total_conflicts"] == 0

    # 8. Log notifikasi Observer tersedia
    notif_resp = client.get("/api/schedules/notifications")
    assert notif_resp.status_code == 200
    assert notif_resp.json()["total"] >= 3

    # 9. Stateless detect endpoint
    detect_resp = client.post(
        "/api/schedules/detect",
        json={
            "schedules": [
                {
                    "id": 10,
                    "kode_mk": "A",
                    "hari": "Senin",
                    "jam_mulai": "08:00",
                    "jam_selesai": "10:00",
                    "ruangan_kode": "R1",
                    "dosen_id": 1,
                },
                {
                    "id": 20,
                    "kode_mk": "B",
                    "hari": "Senin",
                    "jam_mulai": "09:00",
                    "jam_selesai": "11:00",
                    "ruangan_kode": "R2",
                    "dosen_id": 1,
                },
            ]
        },
    )
    assert detect_resp.status_code == 200
    assert detect_resp.json()["conflicts"][0]["type"] == "lecturer_conflict"
    assert detect_resp.json()["conflicts"][0]["affected"] == [10, 20]

    # 10. Seed demo dan UI HTML Dashboard
    seed_resp = client.post("/api/schedules/seed-demo")
    assert seed_resp.status_code == 200

    ui_resp = client.get("/dashboard/conflicts")
    assert ui_resp.status_code == 200
    assert "Conflict Resolver" in ui_resp.text
    assert "/api/schedules" in ui_resp.text
