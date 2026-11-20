from __future__ import annotations

from datetime import datetime, time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.schedule import ScheduleError, normalize_hari


class RoomCreate(BaseModel):
    kode: str = Field(..., min_length=1, max_length=20)
    nama: str = Field(default="", max_length=100)
    kapasitas: int = Field(..., gt=0)
    gedung: str | None = Field(default=None, max_length=50)

    @model_validator(mode="before")
    @classmethod
    def accept_kode_ruangan_alias(cls, data: Any) -> Any:
        if isinstance(data, dict) and "kode" not in data and "kode_ruangan" in data:
            copied = dict(data)
            copied["kode"] = copied.get("kode_ruangan")
            return copied
        return data


class RoomResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    kode: str
    kode_ruangan: str
    nama: str
    kapasitas: int
    gedung: str | None = None


class LecturerCreate(BaseModel):
    nidn: str = Field(..., min_length=1, max_length=20)
    nama: str = Field(..., min_length=1, max_length=120)


class LecturerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nidn: str
    nama: str


class ClassCreate(BaseModel):
    kode_mk: str = Field(..., min_length=1, max_length=10)
    nama_kelas: str = Field(..., min_length=1, max_length=20)
    kuota: int = Field(default=40, gt=0)
    semester: str = Field(default="20251", min_length=1, max_length=10)


class ClassResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kode_mk: str
    nama_mk: str = ""
    nama_kelas: str
    kuota: int
    semester: str


class ScheduleCreate(BaseModel):
    kelas_id: int = Field(..., gt=0)
    ruangan_kode: str = Field(..., min_length=1, max_length=20)
    dosen_id: int = Field(..., gt=0)
    hari: int | str
    jam_mulai: time = Field(..., description="Format HH:MM, misal 08:00")
    jam_selesai: time = Field(..., description="Format HH:MM, misal 10:00")
    force: bool = False

    @field_validator("hari")
    @classmethod
    def validate_hari(cls, v: int | str) -> int:
        try:
            return normalize_hari(v)
        except ScheduleError as exc:
            raise ValueError(str(exc)) from exc

    @model_validator(mode="after")
    def validate_time_order(self) -> "ScheduleCreate":
        if self.jam_mulai >= self.jam_selesai:
            raise ValueError("jam_mulai harus lebih awal daripada jam_selesai")
        return self


class ScheduleUpdate(BaseModel):
    kelas_id: int | None = Field(default=None, gt=0)
    ruangan_kode: str | None = Field(default=None, min_length=1, max_length=20)
    dosen_id: int | None = Field(default=None, gt=0)
    hari: int | str | None = None
    jam_mulai: time | None = None
    jam_selesai: time | None = None
    force: bool = False

    @field_validator("hari")
    @classmethod
    def validate_hari(cls, v: int | str | None) -> int | None:
        if v is None:
            return None
        try:
            return normalize_hari(v)
        except ScheduleError as exc:
            raise ValueError(str(exc)) from exc

    @model_validator(mode="after")
    def validate_time_order(self) -> "ScheduleUpdate":
        if (
            self.jam_mulai is not None
            and self.jam_selesai is not None
            and self.jam_mulai >= self.jam_selesai
        ):
            raise ValueError("jam_mulai harus lebih awal daripada jam_selesai")
        return self


class ScheduleResponse(BaseModel):
    id: int
    kelas_id: int
    kode_mk: str
    nama_mk: str
    nama_kelas: str
    kuota: int
    terdaftar: int
    ruangan_kode: str
    ruangan_nama: str
    kapasitas: int
    dosen_id: int
    dosen_nidn: str
    dosen: str
    semester: str
    hari: int
    hari_nama: str
    jam_mulai: str
    jam_selesai: str
    jam: str
    enrolled_count: int
    sequence: int = 0


class ScheduleMutationResponse(BaseModel):
    schedule: ScheduleResponse
    invalidated_krs_nims: list[str] = Field(default_factory=list)
    notifications_sent: list[dict[str, Any]] = Field(default_factory=list)
    conflicts: list[dict[str, Any]] = Field(default_factory=list)
    outbox_event_id: str | None = None


class ScheduleDeleteResponse(BaseModel):
    detail: str
    deleted_schedule_id: int
    invalidated_krs_nims: list[str] = Field(default_factory=list)
    notifications_sent: list[dict[str, Any]] = Field(default_factory=list)
    outbox_event_id: str | None = None


class ConflictDetectItem(BaseModel):
    id: int | None = None
    kode_mk: str = ""
    nama_mk: str | None = None
    hari: int | str
    jam_mulai: time | None = None
    jam_selesai: time | None = None
    ruangan_kode: str = ""
    ruangan: str | None = None
    dosen_id: int | None = None
    dosen: str = ""

    @field_validator("hari")
    @classmethod
    def validate_hari(cls, v: int | str) -> int:
        try:
            return normalize_hari(v)
        except ScheduleError as exc:
            raise ValueError(str(exc)) from exc

    @model_validator(mode="after")
    def validate_times(self) -> "ConflictDetectItem":
        if self.jam_mulai is not None and self.jam_selesai is not None:
            if self.jam_mulai >= self.jam_selesai:
                raise ValueError("jam_mulai harus lebih awal daripada jam_selesai")
        return self


class ConflictDetectRequest(BaseModel):
    schedules: list[ConflictDetectItem]


class ConflictItemResponse(BaseModel):
    type: Literal["room_conflict", "lecturer_conflict"]
    affected: list[int]
    affected_schedules: list[dict[str, Any]] = Field(default_factory=list)
    detail: str = ""


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


class OutboxItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    event_id: str
    payload: dict[str, Any]
    status: str
    attempts: int
    last_error: str | None = None
    created_at: datetime
    processed_at: datetime | None = None


class OutboxListResponse(BaseModel):
    total: int
    items: list[OutboxItemResponse]
