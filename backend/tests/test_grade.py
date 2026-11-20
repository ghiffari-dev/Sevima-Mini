from __future__ import annotations

from datetime import date, time
from decimal import Decimal
import pytest
from fastapi.testclient import TestClient
from hypothesis import given, settings as h_settings, strategies as st
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.database import get_db as get_orm_db
from app.core.security import create_access_token
from app.main import app
from app.models.base import Base
from app.models.calon_mahasiswa import CalonMahasiswa
from app.models.grade import (
    AlasanWajibError,
    GradeForbiddenError,
    GradeHistory,
    GradeNotFoundError,
    PresensiKurangError,
    SkalaNilai,
    ensure_riwayat_nilai_view,
    seed_skala_nilai,
)
from app.models.jalur_masuk import JalurMasuk
from app.models.krs import KRS, KRSDetail, KRSStatus, MataKuliah
from app.models.program_studi import ProgramStudi
from app.models.schedule import Dosen as DosenJadwal, Jadwal, Kelas as KelasJadwal, Ruangan
from app.routers.grade import get_presensi_port
from app.services.gpa_calculator import (
    GPACalculator,
    NilaiRecord,
    NilaiRepo,
    Skala,
    calculate_ipk_sql,
    hitung_ipk,
    hitung_ips,
)
from app.services.grade_service import GradeService, StubPresensiPort
from app.services.krs_validator import PrerequisiteValidator, KRSContext

SKALA_SEMENTARA: dict[str, Skala] = {
    "A": Skala(Decimal("4.00"), True),
    "B": Skala(Decimal("3.00"), True),
    "C": Skala(Decimal("2.00"), True),
    "D": Skala(Decimal("1.00"), False),
    "E": Skala(Decimal("0.00"), False),
}

REKOR_RINA: list[NilaiRecord] = [
    NilaiRecord("MA101", "20241", 3, "E"),
    NilaiRecord("IF101", "20241", 4, "A"),
    NilaiRecord("UN101", "20241", 2, "B"),
    NilaiRecord("MA101", "20242", 3, "B"),
    NilaiRecord("IF201", "20242", 3, "C"),
    NilaiRecord("IF202", "20242", 3, "D"),
]


# =====================================================================
# 1. Parameterized Unit Tests: hitung_ipk (>= 10 kasus) & hitung_ips (3)
# =====================================================================


@pytest.mark.parametrize(
    "nama_kasus,records,expected",
    [
        (
            "semua_A",
            [
                NilaiRecord("IF101", "20241", 3, "A"),
                NilaiRecord("IF102", "20241", 4, "A"),
            ],
            Decimal("4.00"),
        ),
        ("semester_awal_tanpa_nilai", [], Decimal("0.00")),
        (
            "ulang_naik_E_ke_B",
            [
                NilaiRecord("MA101", "20241", 3, "E"),
                NilaiRecord("MA101", "20242", 3, "B"),
            ],
            Decimal("3.00"),
        ),
        (
            "ulang_turun_B_ke_C_pakai_terbaik",
            [
                NilaiRecord("MA101", "20241", 3, "B"),
                NilaiRecord("MA101", "20242", 3, "C"),
            ],
            Decimal("3.00"),
        ),
        (
            "sks_mk_ulang_tidak_dihitung_ganda",
            [
                NilaiRecord("MA101", "20241", 3, "E"),
                NilaiRecord("MA101", "20242", 3, "B"),
                NilaiRecord("IF101", "20242", 3, "A"),
            ],
            Decimal("3.50"),
        ),
        (
            "E_tidak_dihitung_di_ipk",
            [
                NilaiRecord("IF101", "20241", 3, "A"),
                NilaiRecord("MA101", "20241", 3, "E"),
            ],
            Decimal("4.00"),
        ),
        (
            "D_tidak_dihitung_di_ipk_asumsi_sementara",
            [
                NilaiRecord("IF101", "20241", 3, "A"),
                NilaiRecord("IF202", "20241", 3, "D"),
            ],
            Decimal("4.00"),
        ),
        (
            "pembulatan_half_up_3_125_jadi_3_13",
            [
                NilaiRecord("MK1", "20241", 3, "A"),  # 12
                NilaiRecord("MK2", "20241", 3, "B"),  # 9
                NilaiRecord("MK3", "20241", 2, "C"),  # 4 -> 25 / 8 = 3.125
            ],
            Decimal("3.13"),
        ),
        (
            "pembulatan_2_666_jadi_2_67",
            [
                NilaiRecord("MK1", "20241", 2, "B"),  # 6
                NilaiRecord("MK2", "20241", 1, "C"),  # 2 -> 8 / 3 = 2.666...
            ],
            Decimal("2.67"),
        ),
        ("kasus_rina_multi_semester", REKOR_RINA, Decimal("3.08")),
        (
            "ulang_tiga_kali_E_A_C_pilih_A",
            [
                NilaiRecord("MA101", "20241", 3, "E"),
                NilaiRecord("MA101", "20242", 3, "A"),
                NilaiRecord("MA101", "20251", 3, "C"),
            ],
            Decimal("4.00"),
        ),
    ],
)
def test_hitung_ipk_berparameter(
    nama_kasus: str, records: list[NilaiRecord], expected: Decimal
) -> None:
    hasil = hitung_ipk(records, SKALA_SEMENTARA)
    assert isinstance(hasil, Decimal), nama_kasus
    assert hasil == expected, f"Gagal pada kasus {nama_kasus}: dapat {hasil}"


@pytest.mark.parametrize(
    "semester,expected",
    [
        ("20241", Decimal("2.44")),  # 22 / 9 (E ikut dihitung)
        ("20242", Decimal("2.00")),  # 18 / 9 (D ikut dihitung)
        ("20251", Decimal("0.00")),  # Belum ada nilai pada semester tersebut
    ],
)
def test_hitung_ips_berparameter(semester: str, expected: Decimal) -> None:
    hasil = hitung_ips(REKOR_RINA, semester, SKALA_SEMENTARA)
    assert isinstance(hasil, Decimal)
    assert hasil == expected


def test_tukar_skala_D_menjadi_lulus_mengubah_ipk_tanpa_ubah_kode() -> None:
    """Jika stakeholder memutuskan D lulus, cukup ubah data skala tanpa mengubah kode."""
    skala_d_lulus = {
        **SKALA_SEMENTARA,
        "D": Skala(Decimal("1.00"), True),
    }
    assert hitung_ipk(REKOR_RINA, skala_d_lulus) == Decimal("2.67")


# =====================================================================
# 2. Property-Based Testing (Hypothesis: 3 properti invarian IPK)
# =====================================================================

KATALOG_MK: tuple[tuple[str, int], ...] = (
    ("IF101", 4),
    ("MA101", 3),
    ("UN101", 2),
    ("IF201", 3),
    ("IF202", 3),
    ("IF301", 1),
    ("IF302", 2),
    ("IF303", 4),
)

record_strategy = st.lists(
    st.builds(
        lambda mk, sem, huruf: NilaiRecord(
            kode_mk=mk[0], semester=sem, sks=mk[1], huruf=huruf
        ),
        mk=st.sampled_from(KATALOG_MK),
        sem=st.sampled_from(["20241", "20242", "20251"]),
        huruf=st.sampled_from(["A", "B", "C", "D", "E"]),
    ),
    max_size=25,
)


@h_settings(max_examples=300)
@given(records=record_strategy)
def test_properti_ipk_selalu_antara_0_dan_4(records: list[NilaiRecord]) -> None:
    ipk = hitung_ipk(records, SKALA_SEMENTARA)
    assert Decimal("0.00") <= ipk <= Decimal("4.00")


@h_settings(max_examples=300)
@given(
    records=record_strategy,
    sks_baru=st.integers(min_value=1, max_value=4),
)
def test_properti_tambah_satu_nilai_A_tidak_menurunkan_ipk(
    records: list[NilaiRecord], sks_baru: int
) -> None:
    ipk_sebelum = hitung_ipk(records, SKALA_SEMENTARA)
    ditambah = list(records) + [NilaiRecord("MK_BARU", "20252", sks_baru, "A")]
    ipk_sesudah = hitung_ipk(ditambah, SKALA_SEMENTARA)
    assert ipk_sesudah >= ipk_sebelum


@h_settings(max_examples=300)
@given(data=st.data(), records=record_strategy)
def test_properti_urutan_rekor_tidak_memengaruhi_ipk(
    data: st.DataObject, records: list[NilaiRecord]
) -> None:
    permuted = data.draw(st.permutations(records))
    assert hitung_ipk(permuted, SKALA_SEMENTARA) == hitung_ipk(records, SKALA_SEMENTARA)


# =====================================================================
# 3. Fixture DB & Integration Tests (Repo, SQL CTE, GradeService, View, FK)
# =====================================================================


def _create_sqlite_session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enable_fk(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    ensure_riwayat_nilai_view(engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine), engine


def _seed_grade_world(db):
    """Mengisi data dummy Rina (90%) & Budi (70%), dosen pengampu, non-pengampu, dan jadwal."""
    seed_skala_nilai(db)

    prodi = ProgramStudi(kode="001", nama="Teknik Informatika", fakultas="Teknik")
    jalur = JalurMasuk(nama="SNBP")
    db.add_all([prodi, jalur])
    db.flush()

    rina = CalonMahasiswa(
        nama_lengkap="Rina (Dummy)",
        email="rina@example.com",
        phone="081234567890",
        tanggal_lahir=date(2005, 4, 12),
        program_studi_id=prodi.id,
        jalur_masuk_id=jalur.id,
        status="approved",
        nim="2025001-0101",
    )
    budi = CalonMahasiswa(
        nama_lengkap="Budi (Dummy)",
        email="budi@example.com",
        phone="081234567891",
        tanggal_lahir=date(2005, 5, 20),
        program_studi_id=prodi.id,
        jalur_masuk_id=jalur.id,
        status="approved",
        nim="2025001-0102",
    )
    ruang = Ruangan(kode="R201", nama="Ruang R201", kapasitas=40)
    dosen_pengampu = DosenJadwal(nidn="00100101", nama="Dr. Pengampu")
    dosen_lain = DosenJadwal(nidn="00100102", nama="Dr. Non Pengampu")

    mk_list = [
        MataKuliah(kode_mk="MA101", nama="Kalkulus 1", sks=3),
        MataKuliah(kode_mk="IF101", nama="Algoritma", sks=4),
        MataKuliah(kode_mk="UN101", nama="Bahasa Inggris", sks=2),
        MataKuliah(kode_mk="IF201", nama="Struktur Data", sks=3, prasyarat=[]),
        MataKuliah(kode_mk="IF202", nama="Basis Data", sks=3),
    ]
    db.add_all([rina, budi, ruang, dosen_pengampu, dosen_lain, *mk_list])
    db.flush()

    # Set prasyarat IF201 -> MA101 untuk menguji PrerequisiteValidator berbasis skala_nilai.lulus
    mk_list[3].prasyarat.append(mk_list[0])
    db.flush()

    kelas_specs = [
        ("MA101", "20241", 1, time(8, 0), time(10, 0)),
        ("IF101", "20241", 2, time(8, 0), time(10, 0)),
        ("UN101", "20241", 3, time(8, 0), time(10, 0)),
        ("MA101", "20242", 1, time(10, 0), time(12, 0)),
        ("IF201", "20242", 2, time(10, 0), time(12, 0)),
        ("IF202", "20242", 3, time(10, 0), time(12, 0)),
    ]
    kelas_map: dict[tuple[str, str], KelasJadwal] = {}
    for kode_mk, sem, hari, mulai, selesai in kelas_specs:
        kls = KelasJadwal(kode_mk=kode_mk, nama_kelas="A", kuota=40, semester=sem)
        db.add(kls)
        db.flush()
        db.add(
            Jadwal(
                kelas_id=kls.id,
                ruangan_kode=ruang.kode,
                dosen_id=dosen_pengampu.id,
                hari=hari,
                jam_mulai=mulai,
                jam_selesai=selesai,
            )
        )
        kelas_map[(kode_mk, sem)] = kls

    krs_rina_1 = KRS(
        nim=rina.nim,
        semester="20241",
        status=KRSStatus.APPROVED,
        dosen_pa_id=dosen_pengampu.id,
    )
    krs_rina_1.details.extend(
        [
            KRSDetail(kode_mk="MA101", kelas_id=kelas_map[("MA101", "20241")].id, nilai="E"),
            KRSDetail(kode_mk="IF101", kelas_id=kelas_map[("IF101", "20241")].id, nilai="A"),
            KRSDetail(kode_mk="UN101", kelas_id=kelas_map[("UN101", "20241")].id, nilai="B"),
        ]
    )
    krs_rina_2 = KRS(
        nim=rina.nim,
        semester="20242",
        status=KRSStatus.APPROVED,
        dosen_pa_id=dosen_pengampu.id,
    )
    krs_rina_2.details.extend(
        [
            KRSDetail(kode_mk="MA101", kelas_id=kelas_map[("MA101", "20242")].id, nilai="B"),
            KRSDetail(kode_mk="IF201", kelas_id=kelas_map[("IF201", "20242")].id, nilai="C"),
            KRSDetail(kode_mk="IF202", kelas_id=kelas_map[("IF202", "20242")].id, nilai="D"),
        ]
    )
    # Semester berjalan Rina (nilai=None) tidak boleh memicu KeyError
    krs_rina_3 = KRS(
        nim=rina.nim,
        semester="20251",
        status=KRSStatus.APPROVED,
        dosen_pa_id=dosen_pengampu.id,
    )
    krs_rina_3.details.append(
        KRSDetail(kode_mk="IF201", kelas_id=kelas_map[("IF201", "20242")].id, nilai=None)
    )

    krs_budi_2 = KRS(
        nim=budi.nim,
        semester="20242",
        status=KRSStatus.APPROVED,
        dosen_pa_id=dosen_pengampu.id,
    )
    krs_budi_2.details.extend(
        [
            KRSDetail(kode_mk="IF201", kelas_id=kelas_map[("IF201", "20242")].id, nilai=None),
            KRSDetail(kode_mk="IF202", kelas_id=kelas_map[("IF202", "20242")].id, nilai=None),
        ]
    )

    db.add_all([krs_rina_1, krs_rina_2, krs_rina_3, krs_budi_2])
    db.commit()

    presensi = StubPresensiPort()
    for kls in kelas_map.values():
        presensi.set_persentase(rina.nim, kls.id, Decimal("90.00"))
        presensi.set_persentase(budi.nim, kls.id, Decimal("70.00"))

    return {
        "rina_nim": rina.nim,
        "budi_nim": budi.nim,
        "dosen_pengampu": dosen_pengampu,
        "dosen_lain": dosen_lain,
        "kelas_map": kelas_map,
        "presensi": presensi,
    }


def test_nilai_repo_gpa_calculator_dan_differential_sql_cte() -> None:
    SessionLocal, _ = _create_sqlite_session_factory()
    with SessionLocal() as db:
        ctx = _seed_grade_world(db)
        calc = GPACalculator(NilaiRepo(db))

        assert calc.calculate_ips(ctx["rina_nim"], "20241") == Decimal("2.44")
        assert calc.calculate_ips(ctx["rina_nim"], "20242") == Decimal("2.00")
        assert calc.calculate_ips(ctx["rina_nim"], "20251") == Decimal("0.00")
        assert calc.calculate_ipk(ctx["rina_nim"]) == Decimal("3.08")
        assert calc.calculate_ipk(ctx["budi_nim"]) == Decimal("0.00")

        # Differential test: SQL CTE + ROW_NUMBER() == GPACalculator Python
        assert calculate_ipk_sql(db, ctx["rina_nim"]) == calc.calculate_ipk(ctx["rina_nim"])
        assert calculate_ipk_sql(db, ctx["budi_nim"]) == calc.calculate_ipk(ctx["budi_nim"])


def test_grade_service_guards_audit_trail_atomik_view_dan_fk_database() -> None:
    SessionLocal, _ = _create_sqlite_session_factory()
    with SessionLocal() as db:
        ctx = _seed_grade_world(db)
        presensi: StubPresensiPort = ctx["presensi"]
        service = GradeService(db=db, presensi=presensi)
        kls_sd_id = ctx["kelas_map"][("IF201", "20242")].id
        kls_bd_id = ctx["kelas_map"][("IF202", "20242")].id
        pengampu_id = ctx["dosen_pengampu"].id
        non_pengampu_id = ctx["dosen_lain"].id

        # 1. Bukan pengampu -> 403 Forbidden (bahkan sebelum menyentuh data mahasiswa)
        with pytest.raises(GradeForbiddenError) as exc_403:
            service.input_nilai(non_pengampu_id, kls_sd_id, "NIM-TIDAK-ADA", "A")
        assert exc_403.value.status_code == 403

        # 2. Pengampu sah tapi mahasiswa tidak ada di kelas -> 404 Not Found
        with pytest.raises(GradeNotFoundError) as exc_404:
            service.input_nilai(pengampu_id, kls_sd_id, "2025001-9999", "A")
        assert exc_404.value.status_code == 404

        # 3. Budi presensi 70% -> 422 PresensiKurangError
        with pytest.raises(PresensiKurangError) as exc_pres:
            service.input_nilai(pengampu_id, kls_sd_id, ctx["budi_nim"], "B")
        assert exc_pres.value.status_code == 422

        # 4. Presensi tepat 75% diizinkan & input pertama dicatat dengan nilai_lama=None (UTC)
        presensi.set_persentase(ctx["budi_nim"], kls_sd_id, Decimal("75"))
        res_first = service.input_nilai(pengampu_id, kls_sd_id, ctx["budi_nim"], "B")
        assert res_first.changed is True
        assert res_first.nilai_lama is None
        assert res_first.nilai_baru == "B"
        assert res_first.history is not None
        assert res_first.history.nilai_lama is None
        assert res_first.history.nilai_baru == "B"
        assert res_first.history.diubah_oleh == pengampu_id
        assert res_first.history.diubah_pada is not None

        # 5. Idempoten saat nilai sama -> tidak menambah grade_history baru
        res_same = service.input_nilai(pengampu_id, kls_sd_id, ctx["budi_nim"], "B")
        assert res_same.changed is False
        assert res_same.history is None
        histories = db.scalars(
            select(GradeHistory).where(GradeHistory.grade_id == res_first.detail.id)
        ).all()
        assert len(histories) == 1

        # 6. Ubah nilai lama tanpa alasan -> 422 AlasanWajibError
        with pytest.raises(AlasanWajibError) as exc_alasan:
            service.input_nilai(pengampu_id, kls_sd_id, ctx["budi_nim"], "A", alasan="   ")
        assert exc_alasan.value.status_code == 422

        # 7. Ubah nilai dengan alasan -> atomik 1 transaksi
        res_edit = service.input_nilai(
            pengampu_id,
            kls_sd_id,
            ctx["budi_nim"],
            "A",
            alasan="Perbaikan nilai tugas besar",
        )
        assert res_edit.changed is True
        assert res_edit.nilai_lama == "B"
        assert res_edit.nilai_baru == "A"
        assert res_edit.history.alasan == "Perbaikan nilai tugas besar"

        # 8. Verifikasi SQL View `riwayat_nilai`
        riwayat = service.get_riwayat_nilai(ctx["budi_nim"])
        assert len(riwayat) == 2
        assert riwayat[0]["nilai_lama"] is None and riwayat[0]["nilai_baru"] == "B"
        assert riwayat[1]["nilai_lama"] == "B" and riwayat[1]["nilai_baru"] == "A"
        assert riwayat[1]["nama_dosen"] == "Dr. Pengampu"
        assert riwayat[1]["kode_mk"] == "IF201"

        # 9. Rollback atomik: jika commit gagal, detail.nilai maupun grade_history tidak tersimpan
        orig_commit = db.commit

        def failing_commit():
            raise RuntimeError("Simulasi kegagalan commit")

        db.commit = failing_commit  # type: ignore[method-assign]
        try:
            with pytest.raises(RuntimeError, match="Simulasi kegagalan commit"):
                service.input_nilai(pengampu_id, kls_bd_id, ctx["rina_nim"], "A", alasan="Uji rollback")
        finally:
            db.commit = orig_commit  # type: ignore[method-assign]

        db.expire_all()
        bd_detail = db.scalars(
            select(KRSDetail)
            .join(KRS, KRSDetail.krs_id == KRS.id)
            .where(KRS.nim == ctx["rina_nim"], KRSDetail.kelas_id == kls_bd_id)
        ).first()
        assert bd_detail is not None
        assert bd_detail.nilai == "D"
        assert (
            db.scalars(
                select(GradeHistory).where(GradeHistory.grade_id == bd_detail.id)
            ).all()
            == []
        )

        # 10. Database FK constraint menolak huruf yang tidak terdaftar di skala_nilai
        bd_detail.nilai = "Z"
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()


def test_prerequisite_validator_membaca_kolom_lulus_dari_skala_nilai() -> None:
    """PrerequisiteValidator membaca SkalaNilai.lulus langsung dari database."""
    SessionLocal, _ = _create_sqlite_session_factory()
    with SessionLocal() as db:
        seed_skala_nilai(db)
        prodi = ProgramStudi(kode="001", nama="TI", fakultas="FT")
        jalur = JalurMasuk(nama="SNBP")
        db.add_all([prodi, jalur])
        db.flush()

        mhs = CalonMahasiswa(
            nama_lengkap="Test Prasyarat",
            email="prasyarat@example.com",
            phone="081234567895",
            tanggal_lahir=date(2005, 1, 1),
            program_studi_id=prodi.id,
            jalur_masuk_id=jalur.id,
            status="approved",
            nim="2025001-0200",
        )
        mk_dasar = MataKuliah(kode_mk="MA101", nama="Kalkulus 1", sks=3)
        mk_lanjut = MataKuliah(
            kode_mk="MA201", nama="Kalkulus 2", sks=3, prasyarat=[mk_dasar]
        )
        db.add_all([mhs, mk_dasar, mk_lanjut])
        db.flush()

        krs_lalu = KRS(nim=mhs.nim, semester="20241", status=KRSStatus.APPROVED, dosen_pa_id=1)
        krs_lalu.details.append(KRSDetail(kode_mk="MA101", nilai="D"))
        db.add(krs_lalu)
        db.commit()

        validator = PrerequisiteValidator()
        ctx = KRSContext(nim=mhs.nim, semester="20242", details=[], mk_baru=mk_lanjut, db=db)

        # Asumsi sementara: D.lulus = False -> gagal prasyarat
        assert validator.check(ctx).ok is False

        # Jika stakeholder menetapkan D lulus di skala_nilai -> langsung lulus tanpa ubah kode
        skala_d = db.get(SkalaNilai, "D")
        assert skala_d is not None
        skala_d.lulus = True
        db.commit()
        assert validator.check(ctx).ok is True


# =====================================================================
# 4. API & UI Integration Tests (TestClient + JWT get_current_dosen)
# =====================================================================


@pytest.fixture()
def grade_api_env():
    SessionLocal, engine = _create_sqlite_session_factory()
    with SessionLocal() as db:
        ctx = _seed_grade_world(db)
        pengampu_info = (ctx["dosen_pengampu"].id, ctx["dosen_pengampu"].nidn)
        non_pengampu_info = (ctx["dosen_lain"].id, ctx["dosen_lain"].nidn)
        kelas_ids = {k: v.id for k, v in ctx["kelas_map"].items()}
        rina_nim = ctx["rina_nim"]
        budi_nim = ctx["budi_nim"]
        presensi = ctx["presensi"]

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_orm_db] = override_get_db
    app.dependency_overrides[get_presensi_port] = lambda: presensi

    try:
        with TestClient(app) as client:
            yield {
                "client": client,
                "SessionLocal": SessionLocal,
                "engine": engine,
                "rina_nim": rina_nim,
                "budi_nim": budi_nim,
                "pengampu_info": pengampu_info,
                "non_pengampu_info": non_pengampu_info,
                "kelas_ids": kelas_ids,
                "presensi": presensi,
            }
    finally:
        app.dependency_overrides.clear()


def _dosen_headers(dosen_info: tuple[int, str]) -> dict[str, str]:
    dosen_id, nidn = dosen_info
    token = create_access_token(
        {
            "sub": f"dosen.{nidn}@sevima.ac.id",
            "role": "dosen",
            "dosen_id": dosen_id,
            "nidn": nidn,
        }
    )
    return {"Authorization": f"Bearer {token}"}


def test_grade_api_auth_validasi_input_edit_ipk_dan_riwayat(grade_api_env) -> None:
    client: TestClient = grade_api_env["client"]
    rina_nim: str = grade_api_env["rina_nim"]
    budi_nim: str = grade_api_env["budi_nim"]
    pengampu_info = grade_api_env["pengampu_info"]
    non_pengampu_info = grade_api_env["non_pengampu_info"]
    kelas_ids = grade_api_env["kelas_ids"]

    kls_bd_id = kelas_ids[("IF202", "20242")]
    kls_sd_id = kelas_ids[("IF201", "20242")]

    # 1. Tanpa token -> 401
    r_no_auth = client.put(
        f"/api/kelas/{kls_bd_id}/nilai/{rina_nim}", json={"huruf": "A"}
    )
    assert r_no_auth.status_code == 401

    # 2. Role bukan dosen (admin_akademik) -> 403
    admin_token = create_access_token({"sub": "admin@sevima.ac.id", "role": "admin_akademik"})
    r_admin = client.put(
        f"/api/kelas/{kls_bd_id}/nilai/{rina_nim}",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"huruf": "A"},
    )
    assert r_admin.status_code == 403

    # 3. Dosen lain non-pengampu -> 403
    r_wrong_dosen = client.put(
        f"/api/kelas/{kls_bd_id}/nilai/{rina_nim}",
        headers=_dosen_headers(non_pengampu_info),
        json={"huruf": "A"},
    )
    assert r_wrong_dosen.status_code == 403

    # 4. Validasi Pydantic NilaiIn -> 422 sebelum masuk servis
    for bad_letter in ("F+", "a", "F", ""):
        r_bad = client.put(
            f"/api/kelas/{kls_bd_id}/nilai/{rina_nim}",
            headers=_dosen_headers(pengampu_info),
            json={"huruf": bad_letter},
        )
        assert r_bad.status_code == 422

    # 5. Budi presensi 70% -> 422
    r_budi = client.put(
        f"/api/kelas/{kls_sd_id}/nilai/{budi_nim}",
        headers=_dosen_headers(pengampu_info),
        json={"huruf": "A"},
    )
    assert r_budi.status_code == 422
    assert "75%" in r_budi.json()["detail"]

    # 6. Cek IPK & IPS awal Rina dikirim sebagai string 2 desimal
    ipk_awal = client.get(f"/api/mahasiswa/{rina_nim}/ipk")
    ips_awal = client.get(f"/api/mahasiswa/{rina_nim}/ips/20241")
    assert ipk_awal.status_code == 200
    assert isinstance(ipk_awal.json()["ipk"], str)
    assert ipk_awal.json()["ipk"] == "3.08"
    assert ips_awal.status_code == 200
    assert isinstance(ips_awal.json()["ips"], str)
    assert ips_awal.json()["ips"] == "2.44"

    # 7. Edit nilai Rina Basis Data (D -> B) tanpa alasan -> 422
    r_no_reason = client.put(
        f"/api/kelas/{kls_bd_id}/nilai/{rina_nim}",
        headers=_dosen_headers(pengampu_info),
        json={"huruf": "B"},
    )
    assert r_no_reason.status_code == 422

    # 8. Edit nilai Rina Basis Data (D -> B) dengan alasan -> 200 & IPK terupdate otomatis
    # Total mutu baru: (9 + 16 + 6 + 6 + 9) = 46, total SKS = 15 -> 46 / 15 = 3.0666 -> "3.07"
    r_ok = client.put(
        f"/api/kelas/{kls_bd_id}/nilai/{rina_nim}",
        headers=_dosen_headers(pengampu_info),
        json={"huruf": "B", "alasan": "Remedial proyek basis data"},
    )
    assert r_ok.status_code == 200
    body_ok = r_ok.json()
    assert body_ok["nilai_lama"] == "D"
    assert body_ok["nilai_baru"] == "B"
    assert body_ok["changed"] is True
    assert isinstance(body_ok["ipk"], str)
    assert body_ok["ipk"] == "3.07"
    assert body_ok["ips"] == "2.67"  # (9 + 6 + 9) / 9 = 24 / 9 = 2.666 -> "2.67"

    # GET /ipk ikut mencerminkan nilai baru (compute-on-read)
    assert client.get(f"/api/mahasiswa/{rina_nim}/ipk").json()["ipk"] == "3.07"

    # 9. Riwayat nilai Rina mencatat perubahan dari view riwayat_nilai
    riwayat_resp = client.get(f"/api/mahasiswa/{rina_nim}/riwayat-nilai")
    assert riwayat_resp.status_code == 200
    hist_items = riwayat_resp.json()
    assert len(hist_items) == 1
    assert hist_items[0]["nilai_lama"] == "D"
    assert hist_items[0]["nilai_baru"] == "B"
    assert hist_items[0]["nama_dosen"] == "Dr. Pengampu"
    assert hist_items[0]["alasan"] == "Remedial proyek basis data"


def test_grade_demo_login_seed_kelas_peserta_dan_ui(grade_api_env) -> None:
    client: TestClient = grade_api_env["client"]

    # Login dosen demo via /api/auth/login
    login_resp = client.post(
        "/api/auth/login",
        json={
            "email": settings.DOSEN_DEMO_EMAIL,
            "password": settings.DOSEN_DEMO_PASSWORD,
        },
    )
    assert login_resp.status_code == 200
    headers = {"Authorization": f"Bearer {login_resp.json()['access_token']}"}

    # Seed demo idempoten
    seed_resp = client.post("/api/grades/seed-demo")
    assert seed_resp.status_code == 200

    # Endpoint statis GET /api/kelas/pengampu tidak tertukar dengan /kelas/{kelas_id}
    pengampu_resp = client.get("/api/kelas/pengampu", headers=headers)
    assert pengampu_resp.status_code == 200
    classes = pengampu_resp.json()
    assert len(classes) >= 1

    target_kls_id = next(
        c["kelas_id"]
        for c in classes
        if c["kode_mk"] == "IF201" and c["semester"] == "20242"
    )
    peserta_resp = client.get(f"/api/kelas/{target_kls_id}/peserta", headers=headers)
    assert peserta_resp.status_code == 200
    peserta = peserta_resp.json()["peserta"]
    by_nim = {p["nim"]: p for p in peserta}
    assert by_nim["2025001-0101"]["bisa_diinput"] is True
    assert by_nim["2025001-0102"]["bisa_diinput"] is False

    # UI HTML /dashboard/grades tersedia
    ui_resp = client.get("/dashboard/grades")
    assert ui_resp.status_code == 200
    assert "text/html" in ui_resp.headers["content-type"]
    assert "/api/kelas/" in ui_resp.text
