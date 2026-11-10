from datetime import date, datetime
from pydantic import BaseModel, EmailStr, Field, field_validator
import re

class CalonMahasiswaCreate(BaseModel):
    nama_lengkap: str = Field(..., min_length=3, max_length=150)
    email: EmailStr
    phone: str = Field(..., description="Nomor HP Indonesia, contoh: 08123456789 atau +628123456789")
    tanggal_lahir: date
    alamat: str | None = None
    program_studi_id: int
    jalur_masuk_id: int

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        # Regex format nomor telepon Indonesia: mulai dengan +62, 62, atau 0, diikuti 9-12 digit
        pattern = r"^(\+62|62|0)[0-9]{9,12}$"
        if not re.match(pattern, v):
            raise ValueError("Format nomor telepon Indonesia tidak valid. Gunakan format 08xxxxxxxxxx atau +628xxxxxxxxxx")
        return v

class CalonMahasiswaResponse(BaseModel):
    id: int
    nama_lengkap: str
    email: str
    phone: str
    tanggal_lahir: date
    alamat: str | None
    program_studi_id: int
    jalur_masuk_id: int
    status: str
    nim: str | None
    created_at: datetime
    approved_at: datetime | None

    class Config:
        from_attributes = True

class DashboardStatsResponse(BaseModel):
    total_pendaftar: int
    pending: int
    approved: int
    rejected: int
