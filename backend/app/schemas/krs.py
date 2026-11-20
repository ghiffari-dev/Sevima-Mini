from datetime import datetime, time
from pydantic import BaseModel, ConfigDict, Field, field_validator


class EnrollmentBase(BaseModel):
    id_enrollment: str

class EnrollmentResponse(EnrollmentBase):
    mahasiswa_id: str
    kelas_id: str

    model_config = ConfigDict(from_attributes=True)

class PendaftaranKRSCreate(BaseModel):
    pilihan_matkul_ids: list[str] = Field(..., description="List ID Kelas atau Course yang dipilih")
    semester: str = Field(default="2026-1", description="Semester pengajuan KRS, contoh: 2026-1")
    dosen_pa_id: str | None = Field(default=None, description="ID Dosen Pembimbing Akademik")

class PendaftaranKRSResponse(BaseModel):
    idPendaftaran: str
    semester: str
    tanggalDaftar: datetime
    status: str
    totalSks: int
    mahasiswa_id: str
    dosen_pa_id: str | None = None
    enrollments: list[EnrollmentResponse] = []

    model_config = ConfigDict(from_attributes=True)


# =====================================================================
# Skema API Endpoint KRS (Minggu 06)
# =====================================================================

class AddCourseRequest(BaseModel):
    kode_mk: str = Field(..., min_length=1, description="Kode mata kuliah yang akan ditambahkan")
    kelas_id: int | None = Field(default=None, description="ID kelas paralel opsional")


class ApproveKRSRequest(BaseModel):
    dosen_pa_id: int
    version: int | None = None


class ReviseKRSRequest(BaseModel):
    dosen_pa_id: int
    catatan: str = Field(..., min_length=1, description="Catatan revisi wajib diisi")
    version: int | None = None

    @field_validator("catatan")
    @classmethod
    def validate_catatan_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Catatan revisi tidak boleh kosong")
        return v.strip()


class CourseOfferingInput(BaseModel):
    kode_mk: str = Field(..., min_length=1)
    nama: str = Field(..., min_length=1)
    sks: int = Field(..., ge=1, le=4)
    hari: int = Field(..., ge=1, le=6)
    jam_mulai: time
    jam_selesai: time
    kelas: str = "A"
    wajib: bool = True
    prasyarat: list[str] = Field(default_factory=list)


class RecommendKRSRequest(BaseModel):
    wajib_codes: list[str] = Field(default_factory=list)
    pilihan_codes: list[str] = Field(default_factory=list)
    max_sks: int = Field(default=24, ge=1, le=24)
    offerings: list[CourseOfferingInput] = Field(default_factory=list)


class KRSActionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nim: str
    semester: str
    status: str
    version: int
    dosen_pa_id: int | None = None
    submitted_at: datetime | None = None
    approved_at: datetime | None = None
    catatan_revisi: str | None = None
    courses: list[str] = Field(default_factory=list)


class KRSRecommendationResponse(BaseModel):
    courses: list[str]
    total_sks: int
    skipped: list[str]
    validated: bool


