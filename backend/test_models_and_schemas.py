import pytest
from datetime import date, time
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.security import get_password_hash, verify_password, create_access_token
from app.models import (
    Base,
    Mahasiswa,
    Dosen,
    Course,
    Kelas,
    Schedule,
    PendaftaranKRS,
    Enrollment,
    Grade,
)
from app.schemas.auth import LoginRequest
from app.schemas.course import CourseCreate, KelasCreate
from app.schemas.krs import PendaftaranKRSCreate
from app.schemas.grade import GradeCreate
from app.schemas.payment import VerifyPaymentRequest
from app.services.krs_validator import (
    KRSValidationContext,
    SelectedClassItem,
    CompletedCourseRecord,
    ScheduleSlot,
    build_krs_validation_chain,
    validate_krs_with_db,
)

def test_security_password_hashing():
    password = "securepassword123"
    hashed = get_password_hash(password)
    assert verify_password(password, hashed) is True
    assert verify_password("wrongpassword", hashed) is False

def test_security_jwt_token():
    token = create_access_token({"sub": "test@sevima.com", "role": "admin"})
    assert isinstance(token, str)
    assert len(token) > 0

def test_login_schema():
    login_data = {"email": "user@sevima.com", "password": "password123"}
    login_req = LoginRequest(**login_data)
    assert login_req.email == "user@sevima.com"
    assert login_req.password == "password123"

def test_course_schema():
    course_data = {"kode": "IF101", "nama": "Pemrograman Berorientasi Objek", "sks": 3}
    course = CourseCreate(**course_data)
    assert course.kode == "IF101"
    assert course.sks == 3

def test_krs_schema():
    krs_data = {"pilihan_matkul_ids": ["IF101-A", "IF102-B"]}
    krs = PendaftaranKRSCreate(**krs_data)
    assert len(krs.pilihan_matkul_ids) == 2
    assert krs.semester == "2026-1"

def test_grade_schema():
    grade_data = {"enrollment_id": "ENR-001", "nilaiAngka": 85.5}
    grade = GradeCreate(**grade_data)
    assert grade.nilaiAngka == 85.5

def test_payment_schema():
    pay_data = {"status_bayar": "Lunas"}
    pay = VerifyPaymentRequest(**pay_data)
    assert pay.status_bayar == "Lunas"


# =====================================================================
# Pengujian Chain of Responsibility Validasi KRS & SQLAlchemy 2.0
# =====================================================================

def test_sks_validator_exact_24_allowed_and_over_24_rejected():
    chain = build_krs_validation_chain()

    # Tepat 24 SKS harus diizinkan (lolos)
    items_24 = [
        SelectedClassItem(id_kelas=f"K-{i}", kode_mk=f"IF10{i}", nama_mk=f"Mata Kuliah {i}", sks=4)
        for i in range(6)
    ]
    ctx_24 = KRSValidationContext(mahasiswa_id="M1", semester_aktif="2026-2", selected_classes=items_24)
    res_24 = chain.validate(ctx_24)
    assert res_24.passed is True

    # 25 SKS harus ditolak dan menyebut nama mata kuliah
    items_25 = items_24 + [SelectedClassItem(id_kelas="K-7", kode_mk="IF107", nama_mk="Pemrograman Web", sks=1)]
    ctx_25 = KRSValidationContext(mahasiswa_id="M1", semester_aktif="2026-2", selected_classes=items_25)
    res_25 = chain.validate(ctx_25)
    assert res_25.passed is False
    assert "25 SKS" in res_25.message
    assert "Pemrograman Web" in res_25.message


def test_duplicate_validator_detects_double_enrollment():
    chain = build_krs_validation_chain()
    items = [
        SelectedClassItem(id_kelas="IF101-A", kode_mk="IF101", nama_mk="Algoritma", sks=3),
        SelectedClassItem(id_kelas="IF101-B", kode_mk="IF101", nama_mk="Algoritma", sks=3),
    ]
    ctx = KRSValidationContext(mahasiswa_id="M1", semester_aktif="2026-2", selected_classes=items)
    res = chain.validate(ctx)
    assert res.passed is False
    assert "Algoritma" in res.message


def test_prerequisite_validator_grade_d_fails_and_grade_c_previous_semester_passes():
    chain = build_krs_validation_chain()
    struktur_data = SelectedClassItem(
        id_kelas="IF201-A",
        kode_mk="IF201",
        nama_mk="Struktur Data",
        sks=3,
        prasyarat=[("IF101", "Algoritma")],
    )

    # Kasus 1: Nilai prasyarat 'D' (meskipun secara string ASCII 'D' > 'C', bobotnya 1.0 < 2.0 -> wajib gagal!)
    ctx_d = KRSValidationContext(
        mahasiswa_id="M1",
        semester_aktif="2026-2",
        selected_classes=[struktur_data],
        completed_courses=[
            CompletedCourseRecord(kode_mk="IF101", nama_mk="Algoritma", semester="2026-1", nilai_huruf="D", bobot=1.0)
        ],
    )
    res_d = chain.validate(ctx_d)
    assert res_d.passed is False
    assert "Struktur Data" in res_d.message
    assert "Algoritma" in res_d.message

    # Kasus 2: Nilai 'C' tetapi diambil di semester yang sama (bukan semester sebelumnya) -> wajib gagal!
    ctx_same_sem = KRSValidationContext(
        mahasiswa_id="M1",
        semester_aktif="2026-2",
        selected_classes=[struktur_data],
        completed_courses=[
            CompletedCourseRecord(kode_mk="IF101", nama_mk="Algoritma", semester="2026-2", nilai_huruf="C", bobot=2.0)
        ],
    )
    assert chain.validate(ctx_same_sem).passed is False

    # Kasus 3: Nilai 'C' (bobot 2.0) pada semester sebelumnya ("2026-1" < "2026-2") -> wajib lolos!
    ctx_c = KRSValidationContext(
        mahasiswa_id="M1",
        semester_aktif="2026-2",
        selected_classes=[struktur_data],
        completed_courses=[
            CompletedCourseRecord(kode_mk="IF101", nama_mk="Algoritma", semester="2026-1", nilai_huruf="C", bobot=2.0)
        ],
    )
    assert chain.validate(ctx_c).passed is True


def test_conflict_validator_interval_overlap():
    chain = build_krs_validation_chain()

    # Jam mulai berbeda (08:00-10:00 vs 09:00-11:00) di hari yang sama -> irisan interval bentrok!
    mk_a = SelectedClassItem(
        id_kelas="IF101-A",
        kode_mk="IF101",
        nama_mk="Basis Data",
        sks=3,
        schedules=[ScheduleSlot(hari="Senin", jam_mulai=time(8, 0), jam_selesai=time(10, 0))],
    )
    mk_b = SelectedClassItem(
        id_kelas="IF102-A",
        kode_mk="IF102",
        nama_mk="Jaringan Komputer",
        sks=3,
        schedules=[ScheduleSlot(hari="Senin", jam_mulai=time(9, 0), jam_selesai=time(11, 0))],
    )
    ctx_overlap = KRSValidationContext(mahasiswa_id="M1", semester_aktif="2026-2", selected_classes=[mk_a, mk_b])
    res_overlap = chain.validate(ctx_overlap)
    assert res_overlap.passed is False
    assert "Basis Data" in res_overlap.message
    assert "Jaringan Komputer" in res_overlap.message

    # Jam bersebelahan (08:00-10:00 dan 10:00-12:00) -> tidak bentrok!
    mk_c = SelectedClassItem(
        id_kelas="IF103-A",
        kode_mk="IF103",
        nama_mk="Sistem Operasi",
        sks=3,
        schedules=[ScheduleSlot(hari="Senin", jam_mulai=time(10, 0), jam_selesai=time(12, 0))],
    )
    ctx_adjacent = KRSValidationContext(mahasiswa_id="M1", semester_aktif="2026-2", selected_classes=[mk_a, mk_c])
    assert chain.validate(ctx_adjacent).passed is True


def test_validate_krs_with_sqlalchemy2_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)

    with SessionLocal() as db:
        dosen = Dosen(id="D1", nama="Dr. Budi", email="dosen@sevima.com", hashed_password="x", nip="198001", keahlian="AI")
        mhs = Mahasiswa(id="M1", nama="Andi", email="andi@sevima.com", hashed_password="x", nim="2025001-0001", jurusan="Informatika")
        c_algo = Course(kode="IF101", nama="Algoritma", sks=3)
        c_sd = Course(kode="IF201", nama="Struktur Data", sks=3, prasyarat=[c_algo])

        k_algo = Kelas(id_kelas="IF101-A", nama_kelas="Algo A", semester="2026-1", kapasitas=30, course_kode="IF101", dosen_id="D1")
        k_sd = Kelas(id_kelas="IF201-A", nama_kelas="SD A", semester="2026-2", kapasitas=30, course_kode="IF201", dosen_id="D1")
        sched_sd = Schedule(hari="Senin", jam="08:00-10:00", jam_mulai="08:00", jam_selesai="10:00", ruangan="R101", kelas_id="IF201-A")

        krs_sem1 = PendaftaranKRS(idPendaftaran="KRS-1", semester="2026-1", status="Approved", totalSks=3, mahasiswa_id="M1", dosen_pa_id="D1")
        enr_sem1 = Enrollment(id_enrollment="ENR-1", mahasiswa_id="M1", kelas_id="IF101-A", pendaftaran_krs_id="KRS-1")
        grade_sem1 = Grade(enrollment_id="ENR-1", nilaiAngka=75.0, nilaiHuruf="B", bobot=3.0)

        db.add_all([dosen, mhs, c_algo, c_sd, k_algo, k_sd, sched_sd, krs_sem1, enr_sem1, grade_sem1])
        db.commit()

        result = validate_krs_with_db(db, mahasiswa_id="M1", kelas_ids=["IF201-A"], semester_aktif="2026-2")
        assert result.passed is True


