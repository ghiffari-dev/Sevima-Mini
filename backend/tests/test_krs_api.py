from __future__ import annotations

from datetime import date, time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import get_db as get_orm_db
from app.main import app
from app.models.base import Base
from app.models.calon_mahasiswa import CalonMahasiswa
from app.models.jalur_masuk import JalurMasuk
from app.models.krs import KRS, KRSStatus, MataKuliah
from app.models.program_studi import ProgramStudi


@pytest.fixture()
def api_client():
    """Menyediakan TestClient FastAPI dengan SQLite in-memory StaticPool terisolasi."""
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

        mhs = CalonMahasiswa(
            nama_lengkap="Rina Wulandari",
            email="rina@example.com",
            phone="081234567890",
            tanggal_lahir=date(2005, 4, 12),
            program_studi_id=prodi.id,
            jalur_masuk_id=jalur.id,
            status="approved",
            nim="2025001-0001",
        )
        kalkulus_1 = MataKuliah(
            kode_mk="MA101",
            nama="Kalkulus I",
            sks=3,
            hari=1,
            jam_mulai=time(10, 0),
            jam_selesai=time(12, 0),
        )
        kalkulus_2 = MataKuliah(
            kode_mk="MA201",
            nama="Kalkulus II",
            sks=3,
            hari=3,
            jam_mulai=time(10, 0),
            jam_selesai=time(12, 0),
            prasyarat=[kalkulus_1],
        )
        basis_data = MataKuliah(
            kode_mk="IF201",
            nama="Basis Data",
            sks=3,
            hari=1,
            jam_mulai=time(8, 0),
            jam_selesai=time(10, 0),
        )
        pbo = MataKuliah(
            kode_mk="IF202",
            nama="Pemrograman Berorientasi Objek",
            sks=3,
            hari=1,
            jam_mulai=time(8, 0),
            jam_selesai=time(10, 0),
        )
        jarkom = MataKuliah(
            kode_mk="IF203",
            nama="Jaringan Komputer",
            sks=3,
            hari=2,
            jam_mulai=time(13, 0),
            jam_selesai=time(15, 0),
        )
        krs_draft = KRS(
            nim="2025001-0001",
            semester="20251",
            status=KRSStatus.DRAFT,
            dosen_pa_id=10,
        )
        db.add_all([mhs, kalkulus_1, kalkulus_2, basis_data, pbo, jarkom, krs_draft])
        db.commit()

    def override_get_orm_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_orm_db] = override_get_orm_db
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def test_tambah_mk_tanpa_prasyarat_error(api_client: TestClient) -> None:
    """Foto 2 & 3: gagal tambah MK tanpa prasyarat -> 400 dengan pesan jelas."""
    resp = api_client.post(
        "/api/krs/2025001-0001/courses",
        json={"kode_mk": "MA201"},
    )
    assert resp.status_code == 400
    assert "Prasyarat tidak terpenuhi: Kalkulus I" in resp.json()["detail"]


def test_jadwal_bentrok_error(api_client: TestClient) -> None:
    """Foto 3: menambah dua MK dengan jadwal sama -> 400 dengan pesan 'Jadwal bentrok'."""
    r1 = api_client.post("/api/krs/2025001-0001/courses", json={"kode_mk": "IF201"})
    assert r1.status_code == 201

    r2 = api_client.post("/api/krs/2025001-0001/courses", json={"kode_mk": "IF202"})
    assert r2.status_code == 400
    assert "Jadwal bentrok" in r2.json()["detail"]


def test_submit_kosong_400_berhasil_200_dan_submit_dua_kali_409(
    api_client: TestClient,
) -> None:
    """Foto 1 & 2: submit KRS kosong -> 400, submit valid -> 200, submit dua kali -> 409."""
    r_empty = api_client.post("/api/krs/2025001-0001/submit")
    assert r_empty.status_code == 400
    assert "KRS kosong" in r_empty.json()["detail"]

    r_add = api_client.post("/api/krs/2025001-0001/courses", json={"kode_mk": "IF201"})
    assert r_add.status_code == 201

    r_ok = api_client.post("/api/krs/2025001-0001/submit")
    assert r_ok.status_code == 200
    body = r_ok.json()
    assert body["status"] == "SUBMITTED"
    assert body["submitted_at"] is not None

    r_twice = api_client.post("/api/krs/2025001-0001/submit")
    assert r_twice.status_code == 409
    assert "Transisi tidak diizinkan: SUBMITTED ke SUBMITTED" in r_twice.json()["detail"]


def test_approve_403_dosen_lain_409_versi_basi_200_sukses_dan_409_locked(
    api_client: TestClient,
) -> None:
    """Foto 2, 3, & Slide Lock: 403 dosen lain, 409 versi basi, 200 approve sah, 409 edit saat APPROVED."""
    api_client.post("/api/krs/2025001-0001/courses", json={"kode_mk": "IF201"})
    sub = api_client.post("/api/krs/2025001-0001/submit")
    assert sub.status_code == 200
    current_version = sub.json()["version"]

    # 1. Dosen lain menekan approve -> 403 Forbidden
    r_403 = api_client.post(
        "/api/krs/2025001-0001/approve",
        json={"dosen_pa_id": 99, "version": current_version},
    )
    assert r_403.status_code == 403

    # 2. Dosen PA sah tetapi memakai version basi -> 409 Conflict
    r_stale = api_client.post(
        "/api/krs/2025001-0001/approve",
        json={"dosen_pa_id": 10, "version": current_version - 1},
    )
    assert r_stale.status_code == 409
    assert "KRS sudah berubah, muat ulang" in r_stale.json()["detail"]

    # 3. Dosen PA sah dengan version terbaru -> 200 APPROVED
    r_ok = api_client.post(
        "/api/krs/2025001-0001/approve",
        json={"dosen_pa_id": 10, "version": current_version},
    )
    assert r_ok.status_code == 200
    assert r_ok.json()["status"] == "APPROVED"
    assert r_ok.json()["approved_at"] is not None

    # 4. Setelah APPROVED, add/remove MK harus ditolak dengan 409 (KRSLockedError)
    r_lock_add = api_client.post("/api/krs/2025001-0001/courses", json={"kode_mk": "IF203"})
    assert r_lock_add.status_code == 409
    assert "tidak bisa diubah" in r_lock_add.json()["detail"]

    r_lock_del = api_client.delete("/api/krs/2025001-0001/courses/IF201")
    assert r_lock_del.status_code == 409
    assert "tidak bisa diubah" in r_lock_del.json()["detail"]


def test_revise_422_catatan_kosong_403_dosen_lain_200_sukses_dan_409_state_salah(
    api_client: TestClient,
) -> None:
    """Foto 2: /revise mengembalikan 422, 403, 200, dan 409 sesuai kondisi."""
    api_client.post("/api/krs/2025001-0001/courses", json={"kode_mk": "IF201"})
    sub = api_client.post("/api/krs/2025001-0001/submit")
    v = sub.json()["version"]

    # 1. Catatan kosong / spasi / hilang -> 422 Unprocessable Entity
    assert (
        api_client.post(
            "/api/krs/2025001-0001/revise",
            json={"dosen_pa_id": 10, "catatan": ""},
        ).status_code
        == 422
    )
    assert (
        api_client.post(
            "/api/krs/2025001-0001/revise",
            json={"dosen_pa_id": 10, "catatan": "   "},
        ).status_code
        == 422
    )
    assert (
        api_client.post(
            "/api/krs/2025001-0001/revise",
            json={"dosen_pa_id": 10},
        ).status_code
        == 422
    )

    # 2. Dosen lain -> 403 Forbidden
    r_403 = api_client.post(
        "/api/krs/2025001-0001/revise",
        json={"dosen_pa_id": 99, "catatan": "Tambahkan SKS", "version": v},
    )
    assert r_403.status_code == 403

    # 3. Dosen PA sah -> 200 REVISION
    r_ok = api_client.post(
        "/api/krs/2025001-0001/revise",
        json={"dosen_pa_id": 10, "catatan": "Tambahkan 1 MK lagi", "version": v},
    )
    assert r_ok.status_code == 200
    assert r_ok.json()["status"] == "REVISION"
    assert r_ok.json()["catatan_revisi"] == "Tambahkan 1 MK lagi"

    # 4. Revise saat status sudah REVISION (bukan SUBMITTED) -> 409 Conflict
    r_409 = api_client.post(
        "/api/krs/2025001-0001/revise",
        json={"dosen_pa_id": 10, "catatan": "Ulangi"},
    )
    assert r_409.status_code == 409


def test_recommend_krs_csp_endpoint(api_client: TestClient) -> None:
    """Foto 8 (Challenge Opsional +10%): rekomendasi CSP memprioritaskan wajib > pilihan dan tervalidasi."""
    resp = api_client.post(
        "/api/krs/2025001-0001/recommend",
        json={
            "wajib_codes": ["IF201", "MA201"],  # IF201 valid, MA201 butuh MA101 (belum lulus)
            "pilihan_codes": ["IF202", "IF203"],  # IF202 bentrok dengan IF201, IF203 aman
            "max_sks": 24,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["validated"] is True
    assert data["total_sks"] <= 24
    # IF201 (wajib) dan IF203 (pilihan tak bentrok) terpilih; IF202 (bentrok) & MA201 (prasyarat) di-skip
    assert set(data["courses"]) == {"IF201", "IF203"}
    assert "MA201" in data["skipped"]
    assert "IF202" in data["skipped"]
