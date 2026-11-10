import sqlite3
from datetime import datetime
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field, field_validator
import re

app = FastAPI(title="PMB Academic System API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = "backend/pmb.db"

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

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
def generate_nim(tahun: int, kode_prodi: str, conn: sqlite3.Connection) -> str:
    cursor = conn.cursor()
    cursor.execute("BEGIN IMMEDIATE;")
    prefix = f"{tahun}{kode_prodi}"
    cursor.execute(
        "SELECT nim FROM calon_mahasiswa WHERE nim LIKE ? ORDER BY nim DESC LIMIT 1;",
        (f"{prefix}%",)
    )
    row = cursor.fetchone()
    if row and row["nim"]:
        try:
            running_num = int(row["nim"].split("-")[-1]) + 1
        except Exception:
            running_num = 1
    else:
        running_num = 1
    return f"{prefix}-{running_num:04d}"

@app.post("/api/pmb/register", status_code=status.HTTP_201_CREATED)
def register_calon_mahasiswa(data: CalonMahasiswaCreate, db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("SELECT id FROM calon_mahasiswa WHERE email = ?;", (data.email,))
    if cursor.fetchone():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email sudah terdaftar.")
    
    cursor.execute("SELECT id FROM program_studi WHERE id = ?;", (data.program_studi_id,))
    if not cursor.fetchone():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Program studi tidak ditemukan.")

    cursor.execute("SELECT id FROM jalur_masuk WHERE id = ?;", (data.jalur_masuk_id,))
    if not cursor.fetchone():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Jalur masuk tidak ditemukan.")

    created_at = datetime.utcnow().isoformat()
    cursor.execute(
        "INSERT INTO calon_mahasiswa (nama_lengkap, email, phone, tanggal_lahir, alamat, program_studi_id, jalur_masuk_id, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?);",
        (data.nama_lengkap, data.email, data.phone, data.tanggal_lahir, data.alamat, data.program_studi_id, data.jalur_masuk_id, created_at)
    )
    db.commit()
    return {"message": "Pendaftaran berhasil", "id": cursor.lastrowid, "status": "pending"}

@app.get("/api/pmb/status/{id}")
def get_status_pendaftar(id: int, db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("SELECT cm.*, ps.nama AS nama_program_studi, ps.kode AS kode_prodi, jm.nama AS nama_jalur_masuk FROM calon_mahasiswa cm JOIN program_studi ps ON cm.program_studi_id = ps.id JOIN jalur_masuk jm ON cm.jalur_masuk_id = jm.id WHERE cm.id = ?;", (id,))
    row = cursor.fetchone()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pendaftar tidak ditemukan.")
    return dict(row)

@app.put("/api/pmb/approve/{id}")
def approve_pendaftar(id: int, db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("SELECT cm.*, ps.kode AS kode_prodi FROM calon_mahasiswa cm JOIN program_studi ps ON cm.program_studi_id = ps.id WHERE cm.id = ?;", (id,))
    row = cursor.fetchone()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pendaftar tidak ditemukan.")
    
    if row["status"] == "approved" and row["nim"]:
        return {"message": "Sudah disetujui (Idempotent)", "nim": row["nim"], "status": "approved"}
        
    tahun = datetime.utcnow().year
    nim = generate_nim(tahun, row["kode_prodi"], db)
    approved_at = datetime.utcnow().isoformat()
    
    cursor.execute("UPDATE calon_mahasiswa SET status = 'approved', nim = ?, approved_at = ? WHERE id = ?;", (nim, approved_at, id))
    db.commit()
    return {"message": "Disetujui dan NIM digenerate", "nim": nim, "status": "approved"}

@app.get("/api/pmb/stats")
def get_dashboard_stats(db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("SELECT COUNT(*) AS total FROM calon_mahasiswa;")
    total = cursor.fetchone()["total"]
    cursor.execute("SELECT COUNT(*) AS count FROM calon_mahasiswa WHERE status = 'pending';")
    pending = cursor.fetchone()["count"]
    cursor.execute("SELECT COUNT(*) AS count FROM calon_mahasiswa WHERE status = 'approved';")
    approved = cursor.fetchone()["count"]
    cursor.execute("SELECT COUNT(*) AS count FROM calon_mahasiswa WHERE status = 'rejected';")
    rejected = cursor.fetchone()["count"]
    return {"total_pendaftar": total, "pending": pending, "approved": approved, "rejected": rejected}

