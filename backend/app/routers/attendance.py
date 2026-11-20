from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db as get_orm_db
from app.core.security import get_optional_bearer_payload
from app.models.attendance import AttendanceError, AttendanceForbiddenError
from app.models.schedule import Dosen as DosenJadwal
from app.schemas.attendance import (
    AIAttendanceAnalyzeRequest,
    AIAttendanceAnalyzeResponse,
    AttendanceScanRequest,
    AttendanceScanResponse,
    ClassAttendanceReportResponse,
    OpenSessionRequest,
    QRSessionInfoResponse,
    StudentAttendanceReportResponse,
)
from app.services.attendance_ai_analyzer import analyze_attendance_records
from app.services.attendance_service import AttendanceService

router = APIRouter()


def get_attendance_service(
    db: Session = Depends(get_orm_db),
) -> AttendanceService:
    """Dependency FastAPI untuk menginjeksikan AttendanceService."""
    return AttendanceService(db=db)


def _resolve_optional_dosen_id(
    payload: dict[str, Any] | None,
    db: Session,
) -> int | None:
    """Mengekstrak dosen_id jika request mengirim Bearer token ber-role dosen."""
    if not payload:
        return None
    role = str(payload.get("role") or "").strip().lower()
    if role in {"admin", "admin_akademik"}:
        return None
    if role != "dosen":
        raise AttendanceForbiddenError(
            "Akses ditolak: hanya Dosen Pengampu atau Admin Akademik yang diizinkan"
        )
    raw_id = payload.get("dosen_id")
    if raw_id is not None:
        try:
            return int(raw_id)
        except (TypeError, ValueError):
            pass
    nidn = str(payload.get("nidn") or "").strip()
    if nidn:
        dosen = db.scalars(
            select(DosenJadwal).where(DosenJadwal.nidn == nidn)
        ).first()
        if dosen is not None:
            return dosen.id
    return None


@router.get("/qr/{schedule_id}")
def get_attendance_qr_image(
    schedule_id: int,
    valid_minutes: int | None = Query(default=None, ge=1, le=240),
    latitude: float | None = Query(default=None, ge=-90.0, le=90.0),
    longitude: float | None = Query(default=None, ge=-180.0, le=180.0),
    radius_m: int | None = Query(default=None, ge=10, le=5000),
    format: str = Query(default="png", pattern="^(png|json)$"),
    auth_payload: dict[str, Any] | None = Depends(get_optional_bearer_payload),
    db: Session = Depends(get_orm_db),
    service: AttendanceService = Depends(get_attendance_service),
):
    """Men-generate QR code presensi berotasi otomatis untuk jadwal kuliah tertentu (Step 1).

    Secara default mengembalikan gambar `image/png` beserta header `X-Attendance-Token`,
    `X-Attendance-Session-Id`, dan `X-Attendance-Window` (atau JSON bila `?format=json`).
    """
    dosen_id = _resolve_optional_dosen_id(auth_payload, db)
    png_bytes, info = service.get_or_open_schedule_qr(
        schedule_id,
        dosen_id=dosen_id,
        valid_minutes=valid_minutes,
        latitude=latitude,
        longitude=longitude,
        radius_m=radius_m,
    )
    if format == "json":
        return QRSessionInfoResponse(**info)

    return Response(
        content=png_bytes,
        media_type="image/png",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "X-Attendance-Token": info["token"],
            "X-Attendance-Session-Id": str(info["session_id"]),
            "X-Attendance-Window": str(info["qr_window"]),
            "X-Attendance-Rotate-Seconds": str(info["rotate_seconds"]),
        },
    )


@router.get(
    "/qr/{schedule_id}/info",
    response_model=QRSessionInfoResponse,
    status_code=status.HTTP_200_OK,
)
def get_attendance_qr_info(
    schedule_id: int,
    valid_minutes: int | None = Query(default=None, ge=1, le=240),
    latitude: float | None = Query(default=None, ge=-90.0, le=90.0),
    longitude: float | None = Query(default=None, ge=-180.0, le=180.0),
    radius_m: int | None = Query(default=None, ge=10, le=5000),
    auth_payload: dict[str, Any] | None = Depends(get_optional_bearer_payload),
    db: Session = Depends(get_orm_db),
    service: AttendanceService = Depends(get_attendance_service),
) -> QRSessionInfoResponse:
    """Mengembalikan metadata JSON sesi presensi dan token QR berotasi aktif."""
    dosen_id = _resolve_optional_dosen_id(auth_payload, db)
    _, info = service.get_or_open_schedule_qr(
        schedule_id,
        dosen_id=dosen_id,
        valid_minutes=valid_minutes,
        latitude=latitude,
        longitude=longitude,
        radius_m=radius_m,
    )
    return QRSessionInfoResponse(**info)


@router.post(
    "/sessions",
    response_model=QRSessionInfoResponse,
    status_code=status.HTTP_201_CREATED,
)
def open_attendance_session(
    body: OpenSessionRequest,
    auth_payload: dict[str, Any] | None = Depends(get_optional_bearer_payload),
    db: Session = Depends(get_orm_db),
    service: AttendanceService = Depends(get_attendance_service),
) -> QRSessionInfoResponse:
    """Membuka sesi presensi baru untuk jadwal kuliah tertentu beserta konfigurasi geofence."""
    dosen_id = _resolve_optional_dosen_id(auth_payload, db)
    session = service.open_session(
        body.schedule_id,
        dosen_id=dosen_id,
        tanggal=body.tanggal,
        pertemuan_ke=body.pertemuan_ke,
        valid_minutes=body.valid_minutes,
        latitude=body.latitude,
        longitude=body.longitude,
        radius_m=body.radius_m,
        reuse_existing=False,
    )
    _, info = service.build_rotating_qr_for_session(session)
    return QRSessionInfoResponse(**info)


@router.post(
    "/sessions/{session_id}/close",
    status_code=status.HTTP_200_OK,
)
def close_attendance_session(
    session_id: int,
    auth_payload: dict[str, Any] | None = Depends(get_optional_bearer_payload),
    db: Session = Depends(get_orm_db),
    service: AttendanceService = Depends(get_attendance_service),
) -> dict[str, Any]:
    """Menutup sesi presensi agar QR tidak dapat di-scan lagi."""
    dosen_id = _resolve_optional_dosen_id(auth_payload, db)
    session = service.close_session(session_id, dosen_id=dosen_id)
    return {
        "session_id": session.id,
        "status": session.status,
        "closed_at": session.closed_at.isoformat() if session.closed_at else None,
        "detail": f"Sesi presensi ID {session.id} berhasil ditutup",
    }


@router.post(
    "/scan",
    response_model=AttendanceScanResponse,
    status_code=status.HTTP_200_OK,
)
def scan_attendance_qr(
    body: AttendanceScanRequest,
    request: Request,
    auth_payload: dict[str, Any] | None = Depends(get_optional_bearer_payload),
    service: AttendanceService = Depends(get_attendance_service),
) -> AttendanceScanResponse:
    """Memvalidasi scan QR presensi mahasiswa (JWT, jadwal, KRS, duplikat, GPS, & waktu) (Step 2)."""
    resolved_nim = (body.nim or "").strip()

    if auth_payload is not None:
        role = str(auth_payload.get("role") or "").strip().lower()
        token_nim = str(auth_payload.get("nim") or "").strip()
        if role == "mahasiswa" and token_nim:
            if resolved_nim and resolved_nim != token_nim:
                raise AttendanceForbiddenError(
                    f"Mahasiswa {token_nim} tidak diizinkan melakukan scan atas nama NIM {resolved_nim}"
                )
            resolved_nim = token_nim

    if not resolved_nim:
        raise AttendanceError(
            "NIM mahasiswa wajib disertakan pada body request atau melalui Bearer token mahasiswa",
            status_code=422,
        )

    client_ip = request.client.host if request.client else None
    result = service.scan_qr(
        token=body.token,
        nim=resolved_nim,
        latitude=body.latitude,
        longitude=body.longitude,
        accuracy_m=body.accuracy_m,
        ip_address=client_ip,
    )
    return AttendanceScanResponse(**result)


@router.get(
    "/reports/student/{nim}",
    response_model=StudentAttendanceReportResponse,
    status_code=status.HTTP_200_OK,
)
def get_student_attendance_report(
    nim: str,
    service: AttendanceService = Depends(get_attendance_service),
) -> StudentAttendanceReportResponse:
    """Mengembalikan laporan persentase kehadiran seorang mahasiswa per mata kuliah (Deliverable 3)."""
    data = service.get_student_report(nim)
    return StudentAttendanceReportResponse(**data)


@router.get(
    "/reports/class/{kelas_id}",
    response_model=ClassAttendanceReportResponse,
    status_code=status.HTTP_200_OK,
)
def get_class_attendance_report(
    kelas_id: int,
    service: AttendanceService = Depends(get_attendance_service),
) -> ClassAttendanceReportResponse:
    """Mengembalikan laporan presensi per kelas beserta daftar mahasiswa warning <75% (Deliverable 3)."""
    data = service.get_class_report(kelas_id)
    return ClassAttendanceReportResponse(**data)


@router.get("/reports/class/{kelas_id}/export.xlsx")
def export_class_attendance_excel(
    kelas_id: int,
    service: AttendanceService = Depends(get_attendance_service),
) -> Response:
    """Mengekspor laporan presensi kelas ke file Excel (.xlsx) untuk dosen (Deliverable 3)."""
    xlsx_bytes, filename = service.export_class_report_excel(kelas_id)
    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.post(
    "/ai-insights",
    response_model=AIAttendanceAnalyzeResponse,
    status_code=status.HTTP_200_OK,
)
def analyze_attendance_with_ai(
    body: AIAttendanceAnalyzeRequest,
) -> AIAttendanceAnalyzeResponse:
    """Menganalisis JSON array `attendance_records` dan menemukan pola & early warning (Step 3)."""
    raw_records = [item.model_dump() for item in body.attendance_records]
    result = analyze_attendance_records(raw_records)
    return AIAttendanceAnalyzeResponse(**result)


@router.get(
    "/ai-insights",
    response_model=AIAttendanceAnalyzeResponse,
    status_code=status.HTTP_200_OK,
)
def get_ai_attendance_insights_from_db(
    kelas_id: int | None = Query(default=None, ge=1),
    semester: str | None = Query(default=None),
    service: AttendanceService = Depends(get_attendance_service),
) -> AIAttendanceAnalyzeResponse:
    """Menganalisis pola presensi & early warning langsung dari sesi presensi di database."""
    result = service.get_ai_insights_from_db(
        kelas_id=kelas_id, semester=semester
    )
    return AIAttendanceAnalyzeResponse(**result)


@router.post("/seed-demo", status_code=status.HTTP_200_OK)
def seed_attendance_demo(
    service: AttendanceService = Depends(get_attendance_service),
) -> dict[str, Any]:
    """Memuat data demo Modul Presensi Minggu 12 (Kelas IF301-A, 5 mahasiswa, 4 sesi historis, & jadwal hari ini)."""
    return service.seed_demo_data()
