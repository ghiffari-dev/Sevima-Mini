from __future__ import annotations

from datetime import date, time
import json
import logging

from fastapi.testclient import TestClient
from hypothesis import given, settings as h_settings, strategies as st
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.database import get_db as get_orm_db
from app.main import app
from app.models.base import Base
from app.models.calon_mahasiswa import CalonMahasiswa
from app.models.jalur_masuk import JalurMasuk
from app.models.krs import (
    Actor,
    KRS,
    KRSDetail,
    KRSLog,
    KRSStatus,
    MataKuliah,
    Notifikasi,
    TransitionError,
)
from app.models.program_studi import ProgramStudi
from app.models.schedule import (
    JadwalKuliah,
    Ruangan,
    ScheduleCapacityError,
    ScheduleConflictError,
)
from app.services import schedule_recommender
from app.services.conflict_detector import check_room_capacity, detect_schedule_conflict
from app.services.interval_tree import IntervalTree, to_minutes
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


# =====================================================================
# 1. Interval Tree & Conflict Detection Tests (Deliverable 1)
# =====================================================================


def test_interval_tree_basic_adjacent_and_nested() -> None:
    tree = IntervalTree()
    assert len(tree) == 0
    assert tree.query_overlaps(480, 600) == []
    assert tree.find_all_overlapping_pairs() == []

    tree.insert(to_minutes("08:00"), to_minutes("10:00"), "A")
    tree.insert(to_minutes("10:00"), to_minutes("12:00"), "B")  # bersebelahan -> tidak bentrok
    tree.insert(to_minutes("09:00"), to_minutes("11:00"), "C")  # irisan dengan A & B
    tree.insert(to_minutes("07:00"), to_minutes("13:00"), "D")  # nested melingkupi A, B, C

    assert len(tree) == 4
    assert tree.query_overlaps(to_minutes("08:00"), to_minutes("10:00")) == ["A", "C", "D"]
    pairs = set(tree.find_all_overlapping_pairs())
    assert ("A", "B") not in pairs
    assert ("A", "C") in pairs
    assert ("B", "C") in pairs
    assert ("A", "D") in pairs
    assert ("B", "D") in pairs
    assert ("C", "D") in pairs


@h_settings(max_examples=250)
@given(
    st.lists(
        st.tuples(st.integers(7 * 60, 18 * 60), st.integers(30, 180)),
        max_size=20,
    )
)
def test_interval_tree_matches_bruteforce_overlaps(
    raw_intervals: list[tuple[int, int]],
) -> None:
    """Property test: IntervalTree selalu menghasilkan pasangan irisan persis sama dengan brute-force O(n^2)."""
    intervals = [(idx, start, start + dur) for idx, (start, dur) in enumerate(raw_intervals)]
    tree = IntervalTree()
    for idx, start, end in intervals:
        tree.insert(start, end, idx)

    tree_pairs = {tuple(sorted(pair)) for pair in tree.find_all_overlapping_pairs()}

    brute_pairs: set[tuple[int, int]] = set()
    for i in range(len(intervals)):
        id_a, s_a, e_a = intervals[i]
        for j in range(i + 1, len(intervals)):
            id_b, s_b, e_b = intervals[j]
            if s_a < e_b and s_b < e_a:
                brute_pairs.add((min(id_a, id_b), max(id_a, id_b)))

    assert tree_pairs == brute_pairs


def test_detect_schedule_conflict_3d_room_lecturer_and_time_overlap() -> None:
    schedules = [
        {
            "id": 1,
            "kode_mk": "MA101",
            "nama_mk": "Kalkulus I",
            "hari": "Senin",
            "jam_mulai": "08:00",
            "jam_selesai": "10:00",
            "ruangan": "A101",
            "dosen": "Dr. Budi",
            "enrolled_nims": ["2025001"],
        },
        {
            "id": 2,
            "kode_mk": "IF201",
            "nama_mk": "Basis Data",
            "hari": "Senin",
            "jam_mulai": "08:30",
            "jam_selesai": "10:30",
            "ruangan": "A101",
            "dosen": "Dr. Siti",
            "enrolled_nims": ["2025002"],
        },
        {
            "id": 3,
            "kode_mk": "IF202",
            "nama_mk": "PBO",
            "hari": "Senin",
            "jam_mulai": "09:00",
            "jam_selesai": "11:00",
            "ruangan": "Lab-1",
            "dosen": "Dr. Budi",
            "enrolled_nims": ["2025001"],  # mahasiswa sama dengan MA101
        },
        {
            "id": 4,
            "kode_mk": "IF203",
            "nama_mk": "Jarkom",
            "hari": "Senin",
            "jam_mulai": "10:00",
            "jam_selesai": "12:00",
            "ruangan": "A101",
            "dosen": "Dr. Budi",
            "enrolled_nims": ["2025001"],
        },
    ]

    conflicts = detect_schedule_conflict(schedules)
    types = [c["type"] for c in conflicts]
    assert "room_conflict" in types
    assert "lecturer_conflict" in types
    assert "time_overlap" in types

    # 1 vs 2 -> room_conflict; 1 vs 3 -> lecturer_conflict + time_overlap;
    # 2 vs 3 -> no room/lecturer/nim match; 2 vs 4 -> room_conflict (08:30-10:30 vs 10:00-12:00);
    # 3 vs 4 -> lecturer_conflict + time_overlap; 1 vs 4 -> bersebelahan (tidak bentrok)
    pair_ids_by_type = {
        (c["type"], tuple(s["id"] for s in c["affected_schedules"])) for c in conflicts
    }
    assert ("room_conflict", (1, 2)) in pair_ids_by_type
    assert ("lecturer_conflict", (1, 3)) in pair_ids_by_type
    assert ("time_overlap", (1, 3)) in pair_ids_by_type
    assert ("room_conflict", (2, 4)) in pair_ids_by_type
    assert ("lecturer_conflict", (3, 4)) in pair_ids_by_type
    assert all((1, 4) != pair for _, pair in pair_ids_by_type)


def test_detect_schedule_conflict_clean_and_capacity_check() -> None:
    clean = [
        {
            "id": 1,
            "kode_mk": "MA101",
            "hari": 1,
            "jam_mulai": "08:00",
            "jam_selesai": "10:00",
            "ruangan": "A101",
            "dosen": "Dr. Budi",
        },
        {
            "id": 2,
            "kode_mk": "IF201",
            "hari": 1,
            "jam_mulai": "10:00",
            "jam_selesai": "12:00",
            "ruangan": "A101",
            "dosen": "Dr. Budi",
        },
        {
            "id": 3,
            "kode_mk": "IF202",
            "hari": 2,
            "jam_mulai": "08:00",
            "jam_selesai": "10:00",
            "ruangan": "A101",
            "dosen": "Dr. Budi",
        },
    ]
    assert detect_schedule_conflict(clean, include_general_overlap=True) == []

    check_room_capacity(40, 40, "A101")
    with pytest.raises(ScheduleCapacityError) as exc_info:
        check_room_capacity(41, 40, "A101")
    assert exc_info.value.status_code == 400


# =====================================================================
# 2. Observer Pattern Notification Tests (Deliverable 2)
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
    mgr.notify("SCHEDULE_CHANGED", {"kode_mk": "IF201", "nama_mk": "Basis Data", "dosen": "Dr. Siti"})
    assert len(mgr.get_logs()) > 0
    mgr.clear_logs()
    assert mgr.get_logs() == []


# =====================================================================
# 3. Hybrid AI-Powered Rescheduler Tests (Deliverable 3 Backend)
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
        {"kode_ruangan": "Lab-Kecil", "kapasitas": 25},  # terlalu kecil (< 40)
        {"kode_ruangan": "A101", "kapasitas": 40},
        {"kode_ruangan": "A102", "kapasitas": 45},
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
        {"kode_ruangan": "Lab-Kecil", "kapasitas": 20},
        {"kode_ruangan": "A102", "kapasitas": 45},
        {"kode_ruangan": "A201", "kapasitas": 50},
    ]

    # LLM mengembalikan 1 slot tidak valid (Lab-Kecil kapasitas 20 < 40),
    # 1 slot bentrok ruangan (Selasa 08:00-10:00 A102), dan 1 slot valid (Rabu 08:00-10:00 A102)
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
# 4. KRS Integration & API / UI Tests (Deliverables 1-5)
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
        mk1 = MataKuliah(
            kode_mk="MA101",
            nama="Kalkulus I",
            sks=3,
            hari=1,
            jam_mulai=time(8, 0),
            jam_selesai=time(10, 0),
        )
        mk2 = MataKuliah(
            kode_mk="IF201",
            nama="Basis Data",
            sks=3,
            hari=2,
            jam_mulai=time(10, 0),
            jam_selesai=time(12, 0),
        )
        mk3 = MataKuliah(
            kode_mk="IF203",
            nama="Jaringan Komputer",
            sks=3,
            hari=3,
            jam_mulai=time(13, 0),
            jam_selesai=time(15, 0),
        )
        r1 = Ruangan(kode_ruangan="A101", nama="Ruang A101", kapasitas=40, gedung="A")
        r2 = Ruangan(kode_ruangan="A102", nama="Ruang A102", kapasitas=45, gedung="A")
        r_small = Ruangan(kode_ruangan="K01", nama="Ruang Kecil", kapasitas=2, gedung="B")

        db.add_all([m1, m2, m3, mk1, mk2, mk3, r1, r2, r_small])
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


def test_schedule_update_and_delete_invalidate_affected_krs_to_revision(
    db_session_and_client,
) -> None:
    TestingSessionLocal, _ = db_session_and_client
    notif_mgr = NotificationManager()

    with TestingSessionLocal() as db:
        # Mahasiswa 1: APPROVED mengambil MA101
        mgr = KRSManager(db, semester="20251", dosen_pa_id=10)
        mgr.add_course("2025001-0001", "MA101")
        krs1 = mgr.submit_krs("2025001-0001")
        mgr.approve_krs("2025001-0001", dosen_pa_id=10, version=krs1.version)

        # Mahasiswa 2: SUBMITTED mengambil MA101
        mgr.add_course("2025001-0002", "MA101")
        mgr.submit_krs("2025001-0002")

        # Mahasiswa 3: APPROVED tetapi mengambil IF203 (tidak terdampak MA101)
        mgr.add_course("2025001-0003", "IF203")
        krs3 = mgr.submit_krs("2025001-0003")
        mgr.approve_krs("2025001-0003", dosen_pa_id=10, version=krs3.version)

        # Direct status assignment masih terblokir oleh @validates("status")
        krs_check = db.scalars(select(KRS).where(KRS.nim == "2025001-0001")).first()
        assert krs_check is not None
        with pytest.raises(TransitionError):
            krs_check.status = KRSStatus.REVISION

        sched_svc = SchedulingService(db, notification_manager=notif_mgr)
        created = sched_svc.create_schedule(
            kode_mk="MA101",
            ruangan_kode="A101",
            dosen="Dr. Budi",
            hari=1,
            jam_mulai="08:00",
            jam_selesai="10:00",
            enrolled_count=30,
        )
        sched_id = created["schedule"]["id"]

        # Update jadwal MA101 -> KRS m1 & m2 pindah ke REVISION, m3 tetap APPROVED
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
        mk1 = db.get(MataKuliah, "MA101")

        assert k1 is not None and k1.status == KRSStatus.REVISION
        assert k1.approved_at is None
        assert k1.catatan_revisi is not None and "MA101" in k1.catatan_revisi
        assert k2 is not None and k2.status == KRSStatus.REVISION
        assert k3 is not None and k3.status == KRSStatus.APPROVED
        assert mk1 is not None and mk1.hari == 2 and mk1.jam_mulai == time(10, 0)

        logs = db.scalars(
            select(KRSLog).where(KRSLog.aksi == "invalidate_schedule_change")
        ).all()
        assert len(logs) == 2

        notifs_db = db.scalars(select(Notifikasi)).all()
        assert any(n.nim == "2025001-0001" for n in notifs_db)
        assert any(n.nim == "2025001-0002" for n in notifs_db)

        # Mahasiswa 1 kini bisa edit dan submit ulang lewat KRSManager
        mgr = KRSManager(db, semester="20251", dosen_pa_id=10)
        resubmitted = mgr.submit_krs("2025001-0001")
        assert resubmitted.status == KRSStatus.SUBMITTED

        # Delete jadwal MA101 -> menginvalidasi KRS kembali ke REVISION
        sched_svc = SchedulingService(db, notification_manager=notif_mgr)
        deleted = sched_svc.delete_schedule(sched_id)
        assert "2025001-0001" in deleted["invalidated_krs_nims"]
        k1_after = db.scalars(select(KRS).where(KRS.nim == "2025001-0001")).first()
        assert k1_after is not None and k1_after.status == KRSStatus.REVISION


def test_schedule_api_endpoints_and_conflict_resolver_ui(
    db_session_and_client,
) -> None:
    _, client = db_session_and_client

    # 1. Buat ruangan & jadwal valid
    room_resp = client.post(
        "/api/schedules/rooms",
        json={"kode_ruangan": "A201", "nama": "Ruang A201", "kapasitas": 50, "gedung": "A"},
    )
    assert room_resp.status_code == 201

    # Kapasitas overflow ditolak 400
    cap_err = client.post(
        "/api/schedules",
        json={
            "kode_mk": "MA101",
            "ruangan_kode": "K01",
            "dosen": "Dr. Budi",
            "hari": 1,
            "jam_mulai": "08:00",
            "jam_selesai": "10:00",
            "enrolled_count": 10,
        },
    )
    assert cap_err.status_code == 400
    assert "melebihi kapasitas" in cap_err.json()["detail"]

    # Buat jadwal pertama
    s1 = client.post(
        "/api/schedules",
        json={
            "kode_mk": "MA101",
            "ruangan_kode": "A101",
            "dosen": "Dr. Budi",
            "hari": "Senin",
            "jam_mulai": "08:00",
            "jam_selesai": "10:00",
            "enrolled_count": 40,
        },
    )
    assert s1.status_code == 201
    s1_id = s1.json()["schedule"]["id"]

    # Jadwal bentrok ditolak 409 jika force=False
    s2_conflict = client.post(
        "/api/schedules",
        json={
            "kode_mk": "IF201",
            "ruangan_kode": "A101",
            "dosen": "Dr. Siti",
            "hari": "Senin",
            "jam_mulai": "08:30",
            "jam_selesai": "10:30",
            "enrolled_count": 30,
            "force": False,
        },
    )
    assert s2_conflict.status_code == 409
    assert s2_conflict.json()["conflicts"][0]["type"] == "room_conflict"

    # Dengan force=True -> tersimpan untuk simulasi resolver UI
    s2_forced = client.post(
        "/api/schedules",
        json={
            "kode_mk": "IF201",
            "ruangan_kode": "A101",
            "dosen": "Dr. Siti",
            "hari": "Senin",
            "jam_mulai": "08:30",
            "jam_selesai": "10:30",
            "enrolled_count": 30,
            "force": True,
        },
    )
    assert s2_forced.status_code == 201

    # Cek GET /api/schedules/conflicts
    conflicts_resp = client.get("/api/schedules/conflicts")
    assert conflicts_resp.status_code == 200
    assert conflicts_resp.json()["total_conflicts"] >= 1

    # Minta 3 saran alternatif untuk MA101
    suggest_resp = client.post(f"/api/schedules/{s1_id}/suggest-alternatives")
    assert suggest_resp.status_code == 200
    recs = suggest_resp.json()["recommendations"]
    assert len(recs) == 3

    # Terapkan rekomendasi pertama via PUT -> bentrok hilang!
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

    # Cek log notifikasi Observer tersedia
    notif_resp = client.get("/api/schedules/notifications")
    assert notif_resp.status_code == 200
    assert notif_resp.json()["total"] >= 3

    # Cek stateless detect endpoint
    detect_resp = client.post(
        "/api/schedules/detect",
        json={
            "schedules": [
                {
                    "kode_mk": "A",
                    "hari": "Senin",
                    "jam_mulai": "08:00",
                    "jam_selesai": "10:00",
                    "ruangan": "R1",
                    "dosen": "D1",
                },
                {
                    "kode_mk": "B",
                    "hari": "Senin",
                    "jam_mulai": "09:00",
                    "jam_selesai": "11:00",
                    "ruangan": "R2",
                    "dosen": "D1",
                },
            ]
        },
    )
    assert detect_resp.status_code == 200
    assert detect_resp.json()["conflicts"][0]["type"] == "lecturer_conflict"

    # Cek seed-demo dan UI HTML Dashboard
    seed_resp = client.post("/api/schedules/seed-demo")
    assert seed_resp.status_code == 200

    ui_resp = client.get("/dashboard/conflicts")
    assert ui_resp.status_code == 200
    assert "Conflict Resolver" in ui_resp.text
    assert "/api/schedules" in ui_resp.text
