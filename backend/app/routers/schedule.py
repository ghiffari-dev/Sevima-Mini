from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.database import get_db as get_orm_db
from app.core.security import require_admin_akademik
from app.models.krs import KRS, MataKuliah
from app.models.schedule import HARI_MAP
from app.schemas.schedule import (
    ClassCreate,
    ClassResponse,
    ConflictDetectRequest,
    ConflictListResponse,
    LecturerCreate,
    LecturerResponse,
    NotificationLogResponse,
    OutboxListResponse,
    RescheduleSuggestionResponse,
    RoomCreate,
    RoomResponse,
    ScheduleCreate,
    ScheduleDeleteResponse,
    ScheduleMutationResponse,
    ScheduleResponse,
    ScheduleUpdate,
)
from app.services.calendar_exporter import export_schedules_to_ics
from app.services.conflict_detector import (
    JadwalSlot,
    detect_conflicts_sweep,
)
from app.services.schedule_observer import default_notification_manager
from app.services.scheduling_service import SchedulingService

router = APIRouter()
ADMIN_DEPS = [Depends(require_admin_akademik)]


def get_scheduling_service(db: Session = Depends(get_orm_db)) -> SchedulingService:
    """Menginjeksikan SchedulingService dengan SQLAlchemy Session & NotificationManager."""
    return SchedulingService(db=db, notification_manager=default_notification_manager)


# ------------------------------------------------------------------
# Endpoint Publik/Mahasiswa: Ekspor iCalendar (.ics)
# Didaftarkan SEBELUM /{schedule_id} agar 'export.ics' tidak diparse sebagai int
# ------------------------------------------------------------------


@router.get("/export.ics", status_code=status.HTTP_200_OK)
def export_calendar_ics(
    semester: str = Query(default="20251"),
    nim: str | None = Query(default=None),
    semester_start: date | None = Query(default=None),
    semester_end: date | None = Query(default=None),
    db: Session = Depends(get_orm_db),
    service: SchedulingService = Depends(get_scheduling_service),
):
    """Mengekspor jadwal kuliah ke format iCalendar (.ics) lengkap dengan UID stabil, RRULE, & SEQUENCE."""
    schedules = service.list_schedules(semester=semester)
    if nim is not None and nim.strip():
        stmt = (
            select(KRS)
            .where(KRS.nim == nim.strip(), KRS.semester == semester)
            .options(selectinload(KRS.details))
        )
        krs = db.scalars(stmt).first()
        if krs is None or not krs.details:
            schedules = []
        else:
            kelas_ids = {d.kelas_id for d in krs.details if d.kelas_id is not None}
            mk_codes = {d.kode_mk for d in krs.details if d.kelas_id is None}
            schedules = [
                j
                for j in schedules
                if (j.kelas_id in kelas_ids)
                or (j.kelas is not None and j.kelas.kode_mk in mk_codes)
            ]

    ics_content = export_schedules_to_ics(
        schedules,
        semester_start=semester_start,
        semester_end=semester_end,
    )
    return Response(
        content=ics_content,
        media_type="text/calendar; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="jadwal-sevima-mini.ics"'
        },
    )


# ------------------------------------------------------------------
# Endpoint Khusus Admin Akademik (RBAC via require_admin_akademik)
# ------------------------------------------------------------------


@router.get("/rooms", response_model=list[RoomResponse], status_code=status.HTTP_200_OK, dependencies=ADMIN_DEPS)
def list_rooms(service: SchedulingService = Depends(get_scheduling_service)):
    """Mengambil seluruh master ruangan beserta kapasitasnya."""
    return service.list_rooms()


@router.post("/rooms", response_model=RoomResponse, status_code=status.HTTP_201_CREATED, dependencies=ADMIN_DEPS)
def create_room(
    body: RoomCreate,
    service: SchedulingService = Depends(get_scheduling_service),
):
    """Menambahkan ruangan baru ke database."""
    return service.create_room(
        kode=body.kode,
        nama=body.nama,
        kapasitas=body.kapasitas,
        gedung=body.gedung,
    )


@router.get("/lecturers", response_model=list[LecturerResponse], status_code=status.HTTP_200_OK, dependencies=ADMIN_DEPS)
def list_lecturers(service: SchedulingService = Depends(get_scheduling_service)):
    """Mengambil seluruh master dosen pengampu."""
    return service.list_lecturers()


@router.post("/lecturers", response_model=LecturerResponse, status_code=status.HTTP_201_CREATED, dependencies=ADMIN_DEPS)
def create_lecturer(
    body: LecturerCreate,
    service: SchedulingService = Depends(get_scheduling_service),
):
    """Menambahkan dosen baru dengan NIDN unik."""
    return service.create_lecturer(nidn=body.nidn, nama=body.nama)


@router.get("/classes", response_model=list[ClassResponse], status_code=status.HTTP_200_OK, dependencies=ADMIN_DEPS)
def list_classes(
    semester: str | None = Query(default="20251"),
    service: SchedulingService = Depends(get_scheduling_service),
):
    """Mengambil daftar kelas paralel beserta kuota dan mata kuliahnya."""
    classes = service.list_classes(semester=semester)
    return [
        ClassResponse(
            id=k.id,
            kode_mk=k.kode_mk,
            nama_mk=k.matakuliah.nama if k.matakuliah else k.kode_mk,
            nama_kelas=k.nama_kelas,
            kuota=k.kuota,
            semester=k.semester,
        )
        for k in classes
    ]


@router.post("/classes", response_model=ClassResponse, status_code=status.HTTP_201_CREATED, dependencies=ADMIN_DEPS)
def create_class(
    body: ClassCreate,
    service: SchedulingService = Depends(get_scheduling_service),
):
    """Menambahkan kelas paralel baru untuk sebuah mata kuliah."""
    k = service.create_class(
        kode_mk=body.kode_mk,
        nama_kelas=body.nama_kelas,
        kuota=body.kuota,
        semester=body.semester,
    )
    return ClassResponse(
        id=k.id,
        kode_mk=k.kode_mk,
        nama_mk=k.matakuliah.nama if k.matakuliah else k.kode_mk,
        nama_kelas=k.nama_kelas,
        kuota=k.kuota,
        semester=k.semester,
    )


@router.get("/courses", status_code=status.HTTP_200_OK, dependencies=ADMIN_DEPS)
def list_courses_catalog(db: Session = Depends(get_orm_db)):
    """Mengambil katalog MataKuliah aktif untuk form penjadwalan di dashboard admin."""
    mks = db.scalars(select(MataKuliah).order_by(MataKuliah.kode_mk.asc())).all()
    return [
        {"kode_mk": mk.kode_mk, "nama": mk.nama, "sks": mk.sks}
        for mk in mks
    ]


@router.get("", response_model=list[ScheduleResponse], status_code=status.HTTP_200_OK, dependencies=ADMIN_DEPS)
def list_schedules(
    semester: str | None = Query(default="20251"),
    service: SchedulingService = Depends(get_scheduling_service),
):
    """Menampilkan daftar seluruh jadwal kuliah pada semester tertentu."""
    schedules = service.list_schedules(semester=semester)
    nims_map = service._nims_by_class_ids(schedules)
    return [
        service.schedule_to_response_dict(j, nims_override=nims_map.get(j.id, set()))
        for j in schedules
    ]


@router.post("", response_model=ScheduleMutationResponse, status_code=status.HTTP_201_CREATED, dependencies=ADMIN_DEPS)
def create_schedule(
    body: ScheduleCreate,
    service: SchedulingService = Depends(get_scheduling_service),
):
    """Membuat jadwal kuliah baru dengan penguncian pesimis, cek bentrok SQL, & cek kapasitas."""
    return service.create_schedule(
        kelas_id=body.kelas_id,
        ruangan_kode=body.ruangan_kode,
        dosen_id=body.dosen_id,
        hari=body.hari,
        jam_mulai=body.jam_mulai,
        jam_selesai=body.jam_selesai,
        force=body.force,
    )


@router.get("/conflicts", response_model=ConflictListResponse, status_code=status.HTTP_200_OK, dependencies=ADMIN_DEPS)
def get_conflicts(
    semester: str = Query(default="20251"),
    service: SchedulingService = Depends(get_scheduling_service),
):
    """Mendeteksi seluruh jadwal bentrok aktif menggunakan Grouping + Sort & Sweep."""
    conflicts = service.get_all_conflicts(semester=semester)
    return {"total_conflicts": len(conflicts), "conflicts": conflicts}


@router.post("/detect", response_model=ConflictListResponse, status_code=status.HTTP_200_OK, dependencies=ADMIN_DEPS)
def detect_conflicts(body: ConflictDetectRequest):
    """Mendeteksi bentrok ruangan & dosen secara stateless memakai Sort & Sweep."""
    slots: list[JadwalSlot] = []
    meta_by_id: dict[int, dict] = {}
    for idx, item in enumerate(body.schedules, start=1):
        if item.jam_mulai is None or item.jam_selesai is None:
            continue
        item_id = item.id if item.id is not None else idx
        ruang = (item.ruangan_kode or item.ruangan or "").strip()
        if item.dosen_id is not None:
            d_id = item.dosen_id
        elif item.dosen.strip():
            d_id = abs(hash(item.dosen.strip().lower())) % 1_000_000_000 + 1
        else:
            d_id = -idx

        slot = JadwalSlot(
            id=item_id,
            hari=int(item.hari),
            jam_mulai=item.jam_mulai,
            jam_selesai=item.jam_selesai,
            ruangan_kode=ruang,
            dosen_id=d_id,
        )
        slots.append(slot)
        meta_by_id[item_id] = {
            "id": item_id,
            "kode_mk": item.kode_mk,
            "nama_mk": item.nama_mk or item.kode_mk,
            "hari": int(item.hari),
            "hari_nama": HARI_MAP[int(item.hari)],
            "jam": f"{item.jam_mulai.strftime('%H:%M')}-{item.jam_selesai.strftime('%H:%M')}",
            "ruangan": ruang,
            "dosen": item.dosen or str(d_id),
        }

    raw_conflicts = detect_conflicts_sweep(slots)
    enriched = []
    for c in raw_conflicts:
        aff_dicts = [meta_by_id[jid] for jid in c.affected if jid in meta_by_id]
        enriched.append(
            {
                "type": c.type,
                "affected": list(c.affected),
                "affected_schedules": aff_dicts,
                "detail": f"{c.type}: jadwal {list(c.affected)}",
            }
        )
    return {"total_conflicts": len(enriched), "conflicts": enriched}


@router.get("/notifications", response_model=NotificationLogResponse, status_code=status.HTTP_200_OK, dependencies=ADMIN_DEPS)
def get_notification_logs(limit: int = Query(default=50, ge=1, le=500)):
    """Mengambil riwayat log notifikasi Observer Pattern (Mahasiswa, Dosen, Admin)."""
    logs = default_notification_manager.get_logs(limit=limit)
    return {"total": len(logs), "logs": logs}


@router.get("/outbox", response_model=OutboxListResponse, status_code=status.HTTP_200_OK, dependencies=ADMIN_DEPS)
def list_outbox_rows(
    limit: int = Query(default=50, ge=1, le=200),
    service: SchedulingService = Depends(get_scheduling_service),
):
    """Mengambil daftar baris Transactional Outbox (pending/sent/failed)."""
    items = service.list_outbox(limit=limit)
    return {"total": len(items), "items": items}


@router.post("/outbox/dispatch", status_code=status.HTTP_200_OK, dependencies=ADMIN_DEPS)
def dispatch_outbox_rows(
    limit: int = Query(default=50, ge=1, le=200),
    service: SchedulingService = Depends(get_scheduling_service),
):
    """Memproses ulang baris Transactional Outbox yang masih berstatus pending."""
    return service.dispatch_pending_outbox(limit=limit)


@router.post("/seed-demo", status_code=status.HTTP_200_OK, dependencies=ADMIN_DEPS)
def seed_demo_data(
    semester: str = Query(default="20251"),
    service: SchedulingService = Depends(get_scheduling_service),
):
    """Mengisi data demo skenario bentrok (4 model domain) untuk Dashboard Admin."""
    return service.seed_demo_data(semester=semester)


@router.get("/{schedule_id}", response_model=ScheduleResponse, status_code=status.HTTP_200_OK, dependencies=ADMIN_DEPS)
def get_schedule(
    schedule_id: int,
    service: SchedulingService = Depends(get_scheduling_service),
):
    """Mengambil detail satu jadwal kuliah berdasarkan ID."""
    jadwal = service.get_schedule(schedule_id)
    return service.schedule_to_response_dict(jadwal)


@router.put("/{schedule_id}", response_model=ScheduleMutationResponse, status_code=status.HTTP_200_OK, dependencies=ADMIN_DEPS)
def update_schedule(
    schedule_id: int,
    body: ScheduleUpdate,
    service: SchedulingService = Depends(get_scheduling_service),
):
    """Memperbarui jadwal, memindahkan KRS terdampak ke REVISION, menulis Outbox, & dispatch setelah komit."""
    return service.update_schedule(
        schedule_id=schedule_id,
        kelas_id=body.kelas_id,
        ruangan_kode=body.ruangan_kode,
        dosen_id=body.dosen_id,
        hari=body.hari,
        jam_mulai=body.jam_mulai,
        jam_selesai=body.jam_selesai,
        force=body.force,
    )


@router.delete("/{schedule_id}", response_model=ScheduleDeleteResponse, status_code=status.HTTP_200_OK, dependencies=ADMIN_DEPS)
def delete_schedule(
    schedule_id: int,
    service: SchedulingService = Depends(get_scheduling_service),
):
    """Menghapus jadwal, memindahkan KRS terdampak ke REVISION, menulis Outbox, & dispatch setelah komit."""
    return service.delete_schedule(schedule_id)


@router.post(
    "/{schedule_id}/suggest-alternatives",
    response_model=RescheduleSuggestionResponse,
    status_code=status.HTTP_200_OK,
    dependencies=ADMIN_DEPS,
)
def suggest_alternatives(
    schedule_id: int,
    top_k: int = Query(default=3, ge=1, le=5),
    use_ai: bool = Query(default=True),
    service: SchedulingService = Depends(get_scheduling_service),
):
    """Menghasilkan 3 rekomendasi jadwal alternatif bebas bentrok & minimal disrupsi."""
    return service.suggest_alternatives(schedule_id, top_k=top_k, use_ai=use_ai)
