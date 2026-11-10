from datetime import datetime
from pydantic import BaseModel, Field

class EnrollmentBase(BaseModel):
    id_enrollment: str
    status: str = "Active"

class EnrollmentResponse(EnrollmentBase):
    mahasiswa_id: str
    kelas_id: str

    class Config:
        from_attributes = True

class PendaftaranKRSCreate(BaseModel):
    pilihan_matkul_ids: list[str] = Field(..., description="List ID Kelas atau Course yang dipilih")

class PendaftaranKRSResponse(BaseModel):
    idPendaftaran: str
    tanggalDaftar: datetime
    status: str
    totalSks: int
    mahasiswa_id: str
    enrollments: list[EnrollmentResponse] = []

    class Config:
        from_attributes = True
