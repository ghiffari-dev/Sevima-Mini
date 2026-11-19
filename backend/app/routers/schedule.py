from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db as get_orm_db
from app.models.krs import MataKuliah
from app.schemas.schedule import (
    ConflictDetectRequest,
    ConflictListResponse,
    NotificationLogResponse,
    RescheduleSuggestionResponse,
    RoomCreate,
    RoomResponse,
    ScheduleCreate,
    ScheduleDeleteResponse,
    ScheduleMutationResponse,
    ScheduleResponse,
    ScheduleUpdate,
)
from app.services.conflict_detector import detect_schedule_conflict
from app.services.schedule_observer import default_notification_manager
from app.services.scheduling_service import SchedulingService

router = APIRouter()


def get_scheduling_service(db: Session = Depends(get_orm_db)) -> SchedulingService:
    """Menginjeksikan SchedulingService dengan SQLAlchemy Session & NotificationManager."""
    return SchedulingService(db=db, notification_manager=default_notification_manager)


@router.get("/rooms", response_model=list[RoomResponse], status_code=status.HTTP_200_OK)
def list_rooms(service: SchedulingService = Depends(get_scheduling_service)):
    """Mengambil seluruh master ruangan beserta kapasitasnya."""
    return service.list_rooms()


@router.post("/rooms", response_model=RoomResponse, status_code=status.HTTP_201_CREATED)
def create_room(
    body: RoomCreate,
    service: SchedulingService = Depends(get_scheduling_service),
):
    """Menambahkan ruangan baru ke database."""
    return service.create_room(
        kode_ruangan=body.kode_ruangan,
        nama=body.nama,
        kapasitas=body.kapasitas,
        gedung=body.gedung,
    )


@router.get("/courses", status_code=status.HTTP_200_OK)
def list_courses_catalog(db: Session = Depends(get_orm_db)):
    """Mengambil katalog MataKuliah aktif untuk form penjadwalan di dashboard admin."""
    mks = db.scalars(select(MataKuliah).order_by(MataKuliah.kode_mk.asc())).all()
    return [
        {"kode_mk": mk.kode_mk, "nama": mk.nama, "sks": mk.sks}
        for mk in mks
    ]


@router.get("", response_model=list[ScheduleResponse], status_code=status.HTTP_200_OK)
def list_schedules(
    semester: str | None = Query(default="20251"),
    service: SchedulingService = Depends(get_scheduling_service),
):
    """Menampilkan daftar seluruh jadwal kuliah pada semester tertentu."""
    schedules = service.list_schedules(semester=semester)
    return [service.schedule_to_response_dict(j) for j in schedules]


@router.post("", response_model=ScheduleMutationResponse, status_code=status.HTTP_201_CREATED)
def create_schedule(
    body: ScheduleCreate,
    service: SchedulingService = Depends(get_scheduling_service),
):
    """Membuat jadwal kuliah baru dengan validasi kapasitas & deteksi bentrok 3D."""
    return service.create_schedule(
        kode_mk=body.kode_mk,
        ruangan_kode=body.ruangan_kode,
        dosen=body.dosen,
        hari=body.hari,
        jam_mulai=body.jam_mulai,
        jam_selesai=body.jam_selesai,
        semester=body.semester,
        enrolled_count=body.enrolled_count,
        force=body.force,
    )


@router.get("/conflicts", response_model=ConflictListResponse, status_code=status.HTTP_200_OK)
def get_conflicts(
    semester: str = Query(default="20251"),
    include_general_overlap: bool = Query(default=False),
    service: SchedulingService = Depends(get_scheduling_service),
):
    """Mendeteksi seluruh jadwal bentrok aktif menggunakan Interval Tree."""
    conflicts = service.get_all_conflicts(
        semester=semester, include_general_overlap=include_general_overlap
    )
    return {"total_conflicts": len(conflicts), "conflicts": conflicts}


@router.post("/detect", response_model=ConflictListResponse, status_code=status.HTTP_200_OK)
def detect_conflicts(body: ConflictDetectRequest):
    """Mendeteksi bentrok jadwal secara stateless untuk daftar jadwal input."""
    conflicts = detect_schedule_conflict(
        [item.model_dump() for item in body.schedules],
        include_general_overlap=body.include_general_overlap,
    )
    return {"total_conflicts": len(conflicts), "conflicts": conflicts}


@router.get("/notifications", response_model=NotificationLogResponse, status_code=status.HTTP_200_OK)
def get_notification_logs(limit: int = Query(default=50, ge=1, le=500)):
    """Mengambil riwayat log notifikasi Observer Pattern (Mahasiswa, Dosen, Admin)."""
    logs = default_notification_manager.get_logs(limit=limit)
    return {"total": len(logs), "logs": logs}


@router.post("/seed-demo", status_code=status.HTTP_200_OK)
def seed_demo_data(
    semester: str = Query(default="20251"),
    service: SchedulingService = Depends(get_scheduling_service),
):
    """Mengisi data demo skenario bentrok (Kalkulus I Senin 08:00 A101) untuk Dashboard Admin."""
    return service.seed_demo_data(semester=semester)


@router.get("/{schedule_id}", response_model=ScheduleResponse, status_code=status.HTTP_200_OK)
def get_schedule(
    schedule_id: int,
    service: SchedulingService = Depends(get_scheduling_service),
):
    """Mengambil detail satu jadwal kuliah berdasarkan ID."""
    jadwal = service.get_schedule(schedule_id)
    return service.schedule_to_response_dict(jadwal)


@router.put("/{schedule_id}", response_model=ScheduleMutationResponse, status_code=status.HTTP_200_OK)
def update_schedule(
    schedule_id: int,
    body: ScheduleUpdate,
    service: SchedulingService = Depends(get_scheduling_service),
):
    """Memperbarui jadwal, memindahkan KRS terdampak ke REVISION, & mengirim notifikasi Observer."""
    return service.update_schedule(
        schedule_id=schedule_id,
        ruangan_kode=body.ruangan_kode,
        dosen=body.dosen,
        hari=body.hari,
        jam_mulai=body.jam_mulai,
        jam_selesai=body.jam_selesai,
        enrolled_count=body.enrolled_count,
        force=body.force,
    )


@router.delete("/{schedule_id}", response_model=ScheduleDeleteResponse, status_code=status.HTTP_200_OK)
def delete_schedule(
    schedule_id: int,
    service: SchedulingService = Depends(get_scheduling_service),
):
    """Menghapus jadwal, memindahkan KRS terdampak ke REVISION, & mengirim notifikasi Observer."""
    return service.delete_schedule(schedule_id)


@router.post(
    "/{schedule_id}/suggest-alternatives",
    response_model=RescheduleSuggestionResponse,
    status_code=status.HTTP_200_OK,
)
def suggest_alternatives(
    schedule_id: int,
    top_k: int = Query(default=3, ge=1, le=5),
    use_ai: bool = Query(default=True),
    service: SchedulingService = Depends(get_scheduling_service),
):
    """Menghasilkan 3 rekomendasi jadwal alternatif bebas bentrok & minimal disrupsi."""
    return service.suggest_alternatives(schedule_id, top_k=top_k, use_ai=use_ai)
