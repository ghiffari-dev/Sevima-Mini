import sqlite3
from typing import Optional, Dict, Any
from app.repositories.pmb_repository import IPMBRepository

class SQLitePMBRepository(IPMBRepository):
    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def find_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        cursor = self.db.cursor()
        cursor.execute("SELECT id FROM calon_mahasiswa WHERE email = ?;", (email,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def find_prodi_by_id(self, prodi_id: int) -> Optional[Dict[str, Any]]:
        cursor = self.db.cursor()
        cursor.execute("SELECT id, kode, nama FROM program_studi WHERE id = ?;", (prodi_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def find_jalur_by_id(self, jalur_id: int) -> Optional[Dict[str, Any]]:
        cursor = self.db.cursor()
        cursor.execute("SELECT id, nama FROM jalur_masuk WHERE id = ?;", (jalur_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def save_calon_mahasiswa(self, data_dict: Dict[str, Any]) -> int:
        cursor = self.db.cursor()
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
                data_dict["created_at"]
            )
        )
        self.db.commit()
        return cursor.lastrowid

    def find_pendaftar_by_id(self, pendaftar_id: int) -> Optional[Dict[str, Any]]:
        cursor = self.db.cursor()
        cursor.execute(
            "SELECT cm.*, ps.nama AS nama_program_studi, ps.kode AS kode_prodi, jm.nama AS nama_jalur_masuk "
            "FROM calon_mahasiswa cm "
            "JOIN program_studi ps ON cm.program_studi_id = ps.id "
            "JOIN jalur_masuk jm ON cm.jalur_masuk_id = jm.id "
            "WHERE cm.id = ?;",
            (pendaftar_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def update_status_and_nim(self, pendaftar_id: int, status: str, nim: Optional[str], approved_at: Optional[str]) -> None:
        cursor = self.db.cursor()
        cursor.execute(
            "UPDATE calon_mahasiswa SET status = ?, nim = ?, approved_at = ? WHERE id = ?;",
            (status, nim, approved_at, pendaftar_id)
        )
        self.db.commit()

    def get_latest_nim_by_prefix(self, prefix: str) -> Optional[str]:
        cursor = self.db.cursor()
        cursor.execute("BEGIN IMMEDIATE;")
        cursor.execute(
            "SELECT nim FROM calon_mahasiswa WHERE nim LIKE ? ORDER BY nim DESC LIMIT 1;",
            (f"{prefix}%",)
        )
        row = cursor.fetchone()
        return row["nim"] if row and row["nim"] else None

    def count_total_pendaftar(self) -> int:
        cursor = self.db.cursor()
        cursor.execute("SELECT COUNT(*) AS total FROM calon_mahasiswa;")
        row = cursor.fetchone()
        return row["total"] if row else 0

    def count_pendaftar_by_status(self, status: str) -> int:
        cursor = self.db.cursor()
        cursor.execute("SELECT COUNT(*) AS total FROM calon_mahasiswa WHERE status = ?;", (status,))
        row = cursor.fetchone()
        return row["total"] if row else 0
