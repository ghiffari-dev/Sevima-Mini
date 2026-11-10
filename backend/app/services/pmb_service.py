from datetime import datetime
import sqlite3
from fastapi import HTTPException, status

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

class PMBService:
    @staticmethod
    def register_calon_mahasiswa(db: sqlite3.Connection, data_dict: dict) -> int:
        cursor = db.cursor()
        cursor.execute("SELECT id FROM calon_mahasiswa WHERE email = ?;", (data_dict["email"],))
        if cursor.fetchone():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email sudah terdaftar.")
        
        cursor.execute("SELECT id FROM program_studi WHERE id = ?;", (data_dict["program_studi_id"],))
        if not cursor.fetchone():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Program studi tidak ditemukan.")

        cursor.execute("SELECT id FROM jalur_masuk WHERE id = ?;", (data_dict["jalur_masuk_id"],))
        if not cursor.fetchone():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Jalur masuk tidak ditemukan.")

        created_at = datetime.utcnow().isoformat()
        cursor.execute(
            "INSERT INTO calon_mahasiswa (nama_lengkap, email, phone, tanggal_lahir, alamat, program_studi_id, jalur_masuk_id, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?);",
            (
                data_dict["nama_lengkap"],
                data_dict["email"],
                data_dict["phone"],
                data_dict["tanggal_lahir"],
                data_dict.get("alamat"),
                data_dict["program_studi_id"],
                data_dict["jalur_masuk_id"],
                created_at
            )
        )
        db.commit()
        return cursor.lastrowid

    @staticmethod
    def get_status_pendaftar(db: sqlite3.Connection, pendaftar_id: int) -> dict:
        cursor = db.cursor()
        cursor.execute(
            "SELECT cm.*, ps.nama AS nama_program_studi, ps.kode AS kode_prodi, jm.nama AS nama_jalur_masuk "
            "FROM calon_mahasiswa cm "
            "JOIN program_studi ps ON cm.program_studi_id = ps.id "
            "JOIN jalur_masuk jm ON cm.jalur_masuk_id = jm.id "
            "WHERE cm.id = ?;",
            (pendaftar_id,)
        )
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pendaftar tidak ditemukan.")
        return dict(row)

    @staticmethod
    def approve_pendaftar(db: sqlite3.Connection, pendaftar_id: int) -> dict:
        cursor = db.cursor()
        cursor.execute(
            "SELECT cm.*, ps.kode AS kode_prodi "
            "FROM calon_mahasiswa cm "
            "JOIN program_studi ps ON cm.program_studi_id = ps.id "
            "WHERE cm.id = ?;",
            (pendaftar_id,)
        )
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pendaftar tidak ditemukan.")
        
        if row["status"] == "approved" and row["nim"]:
            return {"message": "Sudah disetujui (Idempotent)", "nim": row["nim"], "status": "approved"}
            
        tahun = datetime.utcnow().year
        nim = generate_nim(tahun, row["kode_prodi"], db)
        approved_at = datetime.utcnow().isoformat()
        
        cursor.execute("UPDATE calon_mahasiswa SET status = 'approved', nim = ?, approved_at = ? WHERE id = ?;", (nim, approved_at, pendaftar_id))
        db.commit()
        return {"message": "Disetujui dan NIM digenerate", "nim": nim, "status": "approved"}

    @staticmethod
    def get_dashboard_stats(db: sqlite3.Connection) -> dict:
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
