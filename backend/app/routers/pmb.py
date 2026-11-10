import re
import sqlite3
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, EmailStr, Field, field_validator
from app.main import get_db
from app.repositories.sqlite_pmb_repository import SQLitePMBRepository
from app.services.pmb_service import PMBService

router = APIRouter()

def get_pmb_service(db: sqlite3.Connection = Depends(get_db)) -> PMBService:
    repo = SQLitePMBRepository(db)
    return PMBService(repo)

class CalonMahasiswaCreate(BaseModel):
    nama_lengkap: str = Field(..., min_length=3, max_length=150)
    email: EmailStr
    phone: str = Field(..., description="Nomor HP Indonesia")
    tanggal_lahir: str
    alamat: str | None = None
    program_studi_id: int
    jalur_masuk_id: int

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        pattern = r"^(\+62|62|0)[0-9]{9,12}$"
        if not re.match(pattern, v):
            raise ValueError("Format nomor telepon Indonesia tidak valid")
        return v

@router.post("/register", status_code=status.HTTP_201_CREATED)
def register_calon_mahasiswa(data: CalonMahasiswaCreate, service: PMBService = Depends(get_pmb_service)):
    last_id = service.register_calon_mahasiswa(data.model_dump())
    return {"message": "Pendaftaran berhasil", "id": last_id, "status": "pending"}

@router.get("/status/{id}")
def get_status_pendaftar(id: int, service: PMBService = Depends(get_pmb_service)):
    result = service.get_status_pendaftar(id)
    return result

@router.put("/approve/{id}")
def approve_pendaftar(id: int, service: PMBService = Depends(get_pmb_service)):
    result = service.approve_pendaftar(id)
    return result

@router.get("/stats")
def get_dashboard_stats(service: PMBService = Depends(get_pmb_service)):
    stats = service.get_dashboard_stats()
    return stats



