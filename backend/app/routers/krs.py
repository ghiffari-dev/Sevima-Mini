from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.database import get_db as get_orm_db
from app.models.krs import KRS, MataKuliah
from app.schemas.krs import (
    AddCourseRequest,
    ApproveKRSRequest,
    KRSActionResponse,
    KRSRecommendationResponse,
    RecommendKRSRequest,
    ReviseKRSRequest,
)
from app.services.krs_manager import KRSManager
from app.services.krs_recommender import CourseOffering, recommend_krs_csp

router = APIRouter()


def get_krs_manager(
    db: Session = Depends(get_orm_db),
    semester: str = Query(default="20251", description="Kode semester aktif, misal 20251"),
) -> KRSManager:
    """Menginjeksikan KRSManager dengan SQLAlchemy Session dari core database."""
    return KRSManager(db=db, semester=semester)


def _to_response(krs: KRS) -> KRSActionResponse:
    """Mengonversi entity KRS menjadi KRSActionResponse."""
    return KRSActionResponse(
        id=krs.id,
        nim=krs.nim,
        semester=krs.semester,
        status=krs.status.value,
        version=krs.version,
        dosen_pa_id=krs.dosen_pa_id,
        submitted_at=krs.submitted_at,
        approved_at=krs.approved_at,
        catatan_revisi=krs.catatan_revisi,
        courses=[d.kode_mk for d in krs.details],
    )


@router.post("/{nim}/courses", status_code=status.HTTP_201_CREATED)
def add_course_to_krs(
    nim: str,
    body: AddCourseRequest,
    manager: KRSManager = Depends(get_krs_manager),
):
    """Menambahkan 1 mata kuliah ke kartu KRS mahasiswa (DRAFT/REVISION)."""
    detail = manager.add_course(nim, body.kode_mk)
    return {
        "detail": f"Mata kuliah {detail.kode_mk} berhasil ditambahkan ke KRS",
        "krs_id": detail.krs_id,
        "kode_mk": detail.kode_mk,
        "nama": detail.matakuliah.nama if detail.matakuliah else None,
    }


@router.delete("/{nim}/courses/{kode_mk}", status_code=status.HTTP_200_OK)
def remove_course_from_krs(
    nim: str,
    kode_mk: str,
    manager: KRSManager = Depends(get_krs_manager),
):
    """Menghapus 1 mata kuliah dari kartu KRS mahasiswa (DRAFT/REVISION)."""
    manager.remove_course(nim, kode_mk)
    return {
        "detail": f"Mata kuliah {kode_mk} berhasil dihapus dari KRS",
        "kode_mk": kode_mk,
    }


@router.post("/{nim}/submit", response_model=KRSActionResponse, status_code=status.HTTP_200_OK)
def submit_krs(
    nim: str,
    manager: KRSManager = Depends(get_krs_manager),
):
    """Mengajukan kartu KRS setelah lolos seluruh validasi (200, 400, 409)."""
    krs = manager.submit_krs(nim)
    return _to_response(krs)


@router.post("/{nim}/approve", response_model=KRSActionResponse, status_code=status.HTTP_200_OK)
def approve_krs(
    nim: str,
    body: ApproveKRSRequest,
    manager: KRSManager = Depends(get_krs_manager),
):
    """Menyetujui kartu KRS oleh Dosen PA sebagai satu unit kerja ACID (200, 403, 409)."""
    krs = manager.approve_krs(nim, dosen_pa_id=body.dosen_pa_id, version=body.version)
    return _to_response(krs)


@router.post("/{nim}/revise", response_model=KRSActionResponse, status_code=status.HTTP_200_OK)
def revise_krs(
    nim: str,
    body: ReviseKRSRequest,
    manager: KRSManager = Depends(get_krs_manager),
):
    """Meminta revisi kartu KRS oleh Dosen PA dengan catatan wajib (200, 403, 409, 422)."""
    krs = manager.revise_krs(
        nim,
        dosen_pa_id=body.dosen_pa_id,
        catatan=body.catatan,
        version=body.version,
    )
    return _to_response(krs)


@router.post(
    "/{nim}/recommend",
    response_model=KRSRecommendationResponse,
    status_code=status.HTTP_200_OK,
)
def recommend_krs(
    nim: str,
    body: RecommendKRSRequest,
    semester: str = Query(default="20251", description="Kode semester aktif, misal 20251"),
    db: Session = Depends(get_orm_db),
):
    """Menghasilkan rekomendasi KRS bebas bentrok menggunakan CSP backtracking & divalidasi ulang."""
    offerings: list[CourseOffering] = []

    if body.offerings:
        for item in body.offerings:
            offerings.append(
                CourseOffering(
                    kode_mk=item.kode_mk,
                    nama=item.nama,
                    sks=item.sks,
                    hari=item.hari,
                    jam_mulai=item.jam_mulai,
                    jam_selesai=item.jam_selesai,
                    kelas=item.kelas,
                    wajib=item.wajib,
                    prasyarat=item.prasyarat or None,
                )
            )
    else:
        requested_codes = list(dict.fromkeys(body.wajib_codes + body.pilihan_codes))
        if requested_codes:
            stmt = (
                select(MataKuliah)
                .where(MataKuliah.kode_mk.in_(requested_codes))
                .options(selectinload(MataKuliah.prasyarat))
            )
            mk_map = {mk.kode_mk: mk for mk in db.scalars(stmt).all()}
            wajib_set = set(body.wajib_codes)
            for kode in requested_codes:
                mk = mk_map.get(kode)
                if mk is not None:
                    offerings.append(
                        CourseOffering(
                            kode_mk=mk.kode_mk,
                            nama=mk.nama,
                            sks=mk.sks,
                            hari=mk.hari,
                            jam_mulai=mk.jam_mulai,
                            jam_selesai=mk.jam_selesai,
                            wajib=kode in wajib_set,
                            prasyarat=[p.kode_mk for p in mk.prasyarat] or None,
                        )
                    )

    res = recommend_krs_csp(
        offerings=offerings,
        max_sks=body.max_sks,
        db=db,
        nim=nim,
        semester=semester,
    )
    return KRSRecommendationResponse(
        courses=[o.kode_mk for o in res.selected],
        total_sks=res.total_sks,
        skipped=res.skipped,
        validated=res.validated,
    )
