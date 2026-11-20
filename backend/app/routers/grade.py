from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.database import get_db as get_orm_db
from app.core.security import get_current_dosen
from app.models.schedule import Dosen as DosenJadwal
from app.schemas.grade import (
    GradeHistoryItem,
    IPKResponse,
    IPSResponse,
    KelasPengampuItem,
    KelasPesertaResponse,
    NilaiIn,
    NilaiOut,
)
from app.services.gpa_calculator import GPACalculator
from app.services.grade_service import (
    GradeService,
    PresensiPort,
    default_presensi_stub,
)

router = APIRouter()


def get_presensi_port() -> PresensiPort:
    """Dependency untuk PresensiPort (sementara menggunakan stub sebelum Minggu 12)."""
    return default_presensi_stub


def get_grade_service(
    db: Session = Depends(get_orm_db),
    presensi: PresensiPort = Depends(get_presensi_port),
) -> GradeService:
    """Menginjeksikan GradeService dengan Session DB dan PresensiPort."""
    return GradeService(db=db, presensi=presensi)


# ------------------------------------------------------------------
# Route statis didaftarkan SEBELUM /kelas/{kelas_id}/...
# ------------------------------------------------------------------


@router.get(
    "/kelas/pengampu",
    response_model=list[KelasPengampuItem],
    status_code=status.HTTP_200_OK,
)
def list_kelas_pengampu(
    dosen: DosenJadwal = Depends(get_current_dosen),
    service: GradeService = Depends(get_grade_service),
) -> list[KelasPengampuItem]:
    """Mengembalikan daftar kelas yang diampu oleh dosen yang sedang login."""
    rows = service.list_kelas_pengampu(dosen.id)
    return [KelasPengampuItem(**row) for row in rows]


@router.get(
    "/kelas/{kelas_id}/peserta",
    response_model=KelasPesertaResponse,
    status_code=status.HTTP_200_OK,
)
def list_peserta_kelas(
    kelas_id: int,
    dosen: DosenJadwal = Depends(get_current_dosen),
    service: GradeService = Depends(get_grade_service),
) -> KelasPesertaResponse:
    """Mengembalikan peserta kelas beserta persentase presensi & status kelayakan nilai."""
    data = service.list_peserta_kelas(kelas_id=kelas_id, dosen_id=dosen.id)
    return KelasPesertaResponse(**data)


@router.put(
    "/kelas/{kelas_id}/nilai/{nim}",
    response_model=NilaiOut,
    status_code=status.HTTP_200_OK,
)
def input_nilai_mahasiswa(
    kelas_id: int,
    nim: str,
    body: NilaiIn,
    dosen: DosenJadwal = Depends(get_current_dosen),
    db: Session = Depends(get_orm_db),
    service: GradeService = Depends(get_grade_service),
) -> NilaiOut:
    """Menetapkan atau mengubah nilai huruf (A..E) mahasiswa oleh dosen pengampu (idempoten PUT)."""
    res = service.input_nilai(
        dosen_id=dosen.id,
        kelas_id=kelas_id,
        nim=nim,
        huruf=body.huruf,
        alasan=body.alasan,
    )
    calc = GPACalculator.from_session(db)
    ips_val = calc.calculate_ips(nim, res.semester)
    ipk_val = calc.calculate_ipk(nim)
    detail_msg = (
        f"Nilai {nim} disimpan menjadi {res.nilai_baru}"
        if res.changed
        else f"Nilai {nim} sudah {res.nilai_baru} (tidak ada perubahan)"
    )
    return NilaiOut(
        nim=res.nim,
        kelas_id=res.kelas_id,
        semester=res.semester,
        nilai_lama=res.nilai_lama,
        nilai_baru=res.nilai_baru,
        changed=res.changed,
        presensi_persen=f"{res.presensi_persen}",
        ips=f"{ips_val:.2f}",
        ipk=f"{ipk_val:.2f}",
        history_id=res.history.id if res.history is not None else None,
        detail=detail_msg,
    )


@router.get(
    "/mahasiswa/{nim}/ips/{semester}",
    response_model=IPSResponse,
    status_code=status.HTTP_200_OK,
)
def get_ips_mahasiswa(
    nim: str,
    semester: str,
    db: Session = Depends(get_orm_db),
) -> IPSResponse:
    """Menghitung IPS mahasiswa pada semester tertentu secara compute-on-read."""
    ips_val = GPACalculator.from_session(db).calculate_ips(nim, semester)
    return IPSResponse(nim=nim, semester=semester, ips=f"{ips_val:.2f}")


@router.get(
    "/mahasiswa/{nim}/ipk",
    response_model=IPKResponse,
    status_code=status.HTTP_200_OK,
)
def get_ipk_mahasiswa(
    nim: str,
    db: Session = Depends(get_orm_db),
) -> IPKResponse:
    """Menghitung IPK kumulatif mahasiswa secara compute-on-read."""
    ipk_val = GPACalculator.from_session(db).calculate_ipk(nim)
    return IPKResponse(nim=nim, ipk=f"{ipk_val:.2f}")


@router.get(
    "/mahasiswa/{nim}/riwayat-nilai",
    response_model=list[GradeHistoryItem],
    status_code=status.HTTP_200_OK,
)
def get_riwayat_nilai_mahasiswa(
    nim: str,
    service: GradeService = Depends(get_grade_service),
) -> list[GradeHistoryItem]:
    """Mengambil jejak audit perubahan nilai mahasiswa dari SQL View `riwayat_nilai`."""
    rows = service.get_riwayat_nilai(nim)
    return [GradeHistoryItem(**row) for row in rows]


@router.post("/grades/seed-demo", status_code=status.HTTP_200_OK)
def seed_grade_demo(
    service: GradeService = Depends(get_grade_service),
) -> dict:
    """Memuat data dummy Rina (90%) & Budi (70%) untuk pengujian form input nilai."""
    return service.seed_demo_data()
