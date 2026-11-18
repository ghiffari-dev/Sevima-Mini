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


def test_krs_manager_and_matakuliah_self_referential_flow():
    """Menguji MataKuliah (sd.prasyarat == [algoritma]), KRS, KRSDetail, dan KRSManager sesuai 8 slide dosen."""
    from app.models.calon_mahasiswa import CalonMahasiswa
    from app.models.jalur_masuk import JalurMasuk
    from app.models.program_studi import ProgramStudi
    from app.models.krs import KRS, KRSDetail, KRSStatus, MataKuliah
    from app.services.krs_manager import KRSError, KRSManager

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)

    with SessionLocal() as db:
        prodi = ProgramStudi(kode="001", nama="Teknik Informatika", fakultas="Teknik")
        jalur = JalurMasuk(nama="SNBP")
        db.add_all([prodi, jalur])
        db.flush()

        mhs = CalonMahasiswa(
            nama_lengkap="Budi Santoso",
            email="budi@example.com",
            phone="081234567890",
            tanggal_lahir=date(2005, 5, 10),
            program_studi_id=prodi.id,
            jalur_masuk_id=jalur.id,
            status="approved",
            nim="2025001-0001",
        )
        algoritma = MataKuliah(
            kode_mk="IF101",
            nama="Algoritma",
            sks=3,
            hari=1,
            jam_mulai=time(8, 0),
            jam_selesai=time(10, 0),
        )
        sd = MataKuliah(
            kode_mk="IF201",
            nama="Struktur Data",
            sks=3,
            hari=2,
            jam_mulai=time(8, 0),
            jam_selesai=time(10, 0),
            prasyarat=[algoritma],
        )
        kalkulus_bentrok = MataKuliah(
            kode_mk="IF202",
            nama="Kalkulus",
            sks=3,
            hari=2,
            jam_mulai=time(9, 0),
            jam_selesai=time(11, 0),
        )
        db.add_all([mhs, algoritma, sd, kalkulus_bentrok])
        db.commit()

        # Pastikan arah join self-referential tidak tertukar (Slide 2: sd.prasyarat == [algoritma])
        assert sd.prasyarat == [algoritma]
        assert algoritma.prasyarat == []

        mgr_sem2 = KRSManager(db, semester="20252", dosen_pa_id=10)

        # 1. Gagal ambil Struktur Data karena Algoritma belum lulus di semester sebelumnya
        with pytest.raises(KRSError, match="Prasyarat tidak terpenuhi"):
            mgr_sem2.add_course("2025001-0001", "IF201")

        # 2. Buat riwayat KRS semester 20251 yang sudah APPROVED dengan nilai Algoritma = 'B'
        krs_sem1 = KRS(nim="2025001-0001", semester="20251", status=KRSStatus.APPROVED, dosen_pa_id=1)
        krs_sem1.details.append(KRSDetail(kode_mk="IF101", nilai="B"))
        db.add(krs_sem1)
        db.commit()

        # 3. Sekarang ambil Struktur Data di semester 20252 berhasil!
        detail_sd = mgr_sem2.add_course("2025001-0001", "IF201")
        assert detail_sd.kode_mk == "IF201"

        # 4. Coba tambah Struktur Data lagi -> ditolak oleh DuplicateValidator ("Sudah ada di KRS")
        with pytest.raises(KRSError, match="Sudah ada di KRS: Struktur Data"):
            mgr_sem2.add_course("2025001-0001", "IF201")

        # 5. Coba tambah Kalkulus yang jamnya beririsan di hari Selasa (09:00-11:00 vs 08:00-10:00) -> ditolak ConflictValidator
        with pytest.raises(KRSError, match="bentrok"):
            mgr_sem2.add_course("2025001-0001", "IF202")

        # 6. Submit & Approve KRS, lalu coba ubah saat APPROVED -> ditolak karena bukan DRAFT/REVISION
        mgr_sem2.submit_krs("2025001-0001")
        mgr_sem2.approve_krs("2025001-0001", dosen_pa_id=10)
        with pytest.raises(KRSError, match="tidak bisa diubah"):
            mgr_sem2.remove_course("2025001-0001", "IF201")


def _buat_krs_berisi(status, dosen_pa_id=10):
    from app.models.krs import KRS, KRSDetail

    krs = KRS(nim="2025001-0001", semester="20251", status=status, dosen_pa_id=dosen_pa_id)
    krs.details.append(KRSDetail(kode_mk="IF101"))
    return krs


def test_krs_state_machine_valid_flow():
    """Menguji seluruh alur transisi sah: DRAFT -> SUBMITTED -> REVISION -> SUBMITTED -> APPROVED."""
    from app.models.krs import KRSStatus

    krs = _buat_krs_berisi(KRSStatus.DRAFT, dosen_pa_id=10)
    assert krs.transition(KRSStatus.SUBMITTED, actor="mahasiswa") == KRSStatus.SUBMITTED
    assert krs.transition(KRSStatus.REVISION, actor="dosen", dosen_id=10) == KRSStatus.REVISION
    assert krs.transition(KRSStatus.SUBMITTED, actor="mahasiswa") == KRSStatus.SUBMITTED
    assert krs.transition(KRSStatus.APPROVED, actor="dosen", dosen_id=10) == KRSStatus.APPROVED


@pytest.mark.parametrize(
    "state_asal,state_tujuan,actor",
    [
        # Dari DRAFT (ilegal)
        ("DRAFT", "DRAFT", "mahasiswa"),
        ("DRAFT", "APPROVED", "mahasiswa"),
        ("DRAFT", "APPROVED", "dosen"),
        ("DRAFT", "REVISION", "mahasiswa"),
        ("DRAFT", "REVISION", "dosen"),
        ("DRAFT", "SUBMITTED", "dosen"),
        # Dari SUBMITTED (ilegal, termasuk submit dua kali & mahasiswa approve sendiri)
        ("SUBMITTED", "DRAFT", "mahasiswa"),
        ("SUBMITTED", "DRAFT", "dosen"),
        ("SUBMITTED", "SUBMITTED", "mahasiswa"),
        ("SUBMITTED", "SUBMITTED", "dosen"),
        ("SUBMITTED", "APPROVED", "mahasiswa"),
        ("SUBMITTED", "REVISION", "mahasiswa"),
        # Dari REVISION (ilegal, termasuk lompat ke APPROVED tanpa submit ulang)
        ("REVISION", "DRAFT", "mahasiswa"),
        ("REVISION", "DRAFT", "dosen"),
        ("REVISION", "REVISION", "mahasiswa"),
        ("REVISION", "REVISION", "dosen"),
        ("REVISION", "APPROVED", "mahasiswa"),
        ("REVISION", "APPROVED", "dosen"),
        ("REVISION", "SUBMITTED", "dosen"),
        # Dari APPROVED (final state, semua transisi keluar ilegal)
        ("APPROVED", "DRAFT", "mahasiswa"),
        ("APPROVED", "SUBMITTED", "mahasiswa"),
        ("APPROVED", "REVISION", "dosen"),
        ("APPROVED", "APPROVED", "dosen"),
    ],
)
def test_krs_state_machine_all_illegal_transitions(state_asal, state_tujuan, actor):
    """Menguji semua transisi ilegal dan memastikan pesan error bahasa Indonesia sesuai format."""
    from app.models.krs import KRSStatus, StateTransitionError

    krs = _buat_krs_berisi(KRSStatus(state_asal), dosen_pa_id=10)
    expected_msg = f"Transisi tidak diizinkan: {state_asal} ke {state_tujuan}"
    with pytest.raises(StateTransitionError, match=expected_msg):
        krs.transition(KRSStatus(state_tujuan), actor=actor, dosen_id=10)


def test_krs_state_machine_guards_empty_krs_wrong_dosen_and_direct_assign():
    """Menguji penolakan KRS kosong, dosen PA berbeda, dan perubahan krs.status langsung."""
    from app.models.krs import KRS, KRSStatus, StateTransitionError

    # 1. Tolak submit jika KRS kosong
    krs_kosong = KRS(nim="2025001-0001", semester="20251", status=KRSStatus.DRAFT, dosen_pa_id=10)
    with pytest.raises(StateTransitionError, match="KRS kosong tidak dapat di-submit"):
        krs_kosong.transition(KRSStatus.SUBMITTED, actor="mahasiswa")

    # 2. Tolak approve/revise jika ditekan oleh dosen lain (bukan krs.dosen_pa_id)
    krs_submitted = _buat_krs_berisi(KRSStatus.SUBMITTED, dosen_pa_id=10)
    with pytest.raises(StateTransitionError, match="Dosen PA"):
        krs_submitted.transition(KRSStatus.APPROVED, actor="dosen", dosen_id=99)
    with pytest.raises(StateTransitionError, match="Dosen PA"):
        krs_submitted.transition(KRSStatus.REVISION, actor="dosen", dosen_id=99)

    # 3. Tolak penulisan krs.status = ... secara langsung di luar transition()
    with pytest.raises(StateTransitionError, match="transition\\(\\)"):
        krs_submitted.status = KRSStatus.APPROVED




