from __future__ import annotations

from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class RoomCreate(BaseModel):
    kode_ruangan: str = Field(..., min_length=1, max_length=20)
    nama: str = Field(..., min_length=1, max_length=100)
    kapasitas: int = Field(..., gt=0)
    gedung: str | None = Field(default=None, max_length=50)


class RoomResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    kode_ruangan: str
    nama: str
    kapasitas: int
    gedung: str | None = None


class ScheduleCreate(BaseModel):
    kode_mk: str = Field(..., min_length=1, max_length=10)
    ruangan_kode: str = Field(..., min_length=1, max_length=20)
    dosen: str = Field(..., min_length=1, max_length=120)
    hari: int | str
    jam_mulai: str = Field(..., description="Format HH:MM, misal 08:00")
    jam_selesai: str = Field(..., description="Format HH:MM, misal 10:00")
    semester: str = Field(default="20251", min_length=1, max_length=10)
    enrolled_count: int = Field(default=0, ge=0)
    force: bool = False


class ScheduleUpdate(BaseModel):
    ruangan_kode: str | None = Field(default=None, min_length=1, max_length=20)
    dosen: str | None = Field(default=None, min_length=1, max_length=120)
    hari: int | str | None = None
    jam_mulai: str | None = None
    jam_selesai: str | None = None
    enrolled_count: int | None = Field(default=None, ge=0)
    force: bool = False


class ScheduleResponse(BaseModel):
    id: int
    kode_mk: str
    nama_mk: str
    ruangan_kode: str
    ruangan_nama: str
    kapasitas: int
    dosen: str
    semester: str
    hari: int
    hari_nama: str
    jam_mulai: str
    jam_selesai: str
    jam: str
    enrolled_count: int


class ScheduleMutationResponse(BaseModel):
    schedule: ScheduleResponse
    invalidated_krs_nims: list[str] = Field(default_factory=list)
    notifications_sent: list[dict[str, Any]] = Field(default_factory=list)
    conflicts: list[dict[str, Any]] = Field(default_factory=list)


class ScheduleDeleteResponse(BaseModel):
    detail: str
    deleted_schedule_id: int
    invalidated_krs_nims: list[str] = Field(default_factory=list)
    notifications_sent: list[dict[str, Any]] = Field(default_factory=list)


class ConflictDetectItem(BaseModel):
    id: int | str | None = None
    kode_mk: str = ""
    nama_mk: str | None = None
    hari: int | str
    jam_mulai: str | None = None
    jam_selesai: str | None = None
    jam: str | None = None
    ruangan: str = ""
    dosen: str = ""
    enrolled_count: int = 0
    kapasitas: int | None = None
    enrolled_nims: list[str] = Field(default_factory=list)


class ConflictDetectRequest(BaseModel):
    schedules: list[ConflictDetectItem]
    include_general_overlap: bool = False


class ConflictItemResponse(BaseModel):
    type: str
    affected_schedules: list[dict[str, Any]]
    detail: str


class ConflictListResponse(BaseModel):
    total_conflicts: int
    conflicts: list[ConflictItemResponse]


class AlternativeSlotResponse(BaseModel):
    hari: str
    hari_num: int
    jam: str
    jam_mulai: str
    jam_selesai: str
    ruangan: str
    kapasitas: int
    reason: str


class RescheduleSuggestionResponse(BaseModel):
    schedule: dict[str, Any]
    source: str
    prompt_preview: str
    recommendations: list[AlternativeSlotResponse]


class NotificationLogResponse(BaseModel):
    total: int
    logs: list[dict[str, Any]]
