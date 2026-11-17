from datetime import datetime
from pydantic import BaseModel, Field

class EnrollmentBase(BaseModel):
    id_enrollment: str

class EnrollmentResponse(EnrollmentBase):
    mahasiswa_id: str
    kelas_id: str

    class Config:
        from_attributes = True

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

    class Config:
        from_attributes = True

