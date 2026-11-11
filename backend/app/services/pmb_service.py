from datetime import datetime
from fastapi import HTTPException, status
from app.repositories.pmb_repository import IPMBRepository

class PMBService:
    def __init__(self, repo: IPMBRepository):
        self.repo = repo

    def generate_nim(self, tahun: int, kode_prodi: str) -> str:
        prefix = f"{tahun}{kode_prodi}"
        latest_nim = self.repo.get_latest_nim_by_prefix(prefix)
        if latest_nim:
            try:
                running_num = int(latest_nim.split("-")[-1]) + 1
            except Exception:
                running_num = 1
        else:
            running_num = 1
        return f"{prefix}-{running_num:04d}"

    def register_calon_mahasiswa(self, data_dict: dict) -> int:
        if self.repo.find_by_email(data_dict["email"]):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email sudah terdaftar.")
        
        if not self.repo.find_prodi_by_id(data_dict["program_studi_id"]):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Program studi tidak ditemukan.")

        if not self.repo.find_jalur_by_id(data_dict["jalur_masuk_id"]):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Jalur masuk tidak ditemukan.")

        data_dict["created_at"] = datetime.utcnow().isoformat()
        return self.repo.save_calon_mahasiswa(data_dict)

    def get_status_pendaftar(self, pendaftar_id: int) -> dict:
        row = self.repo.find_pendaftar_by_id(pendaftar_id)
        if not row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pendaftar tidak ditemukan.")
        return row

    def approve_pendaftar(self, pendaftar_id: int) -> dict:
        row = self.repo.find_pendaftar_by_id(pendaftar_id)
        if not row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pendaftar tidak ditemukan.")
        
        if row["status"] == "approved":
            return {"id": row["id"], "message": "Sudah disetujui (Idempotent)", "nim": row["nim"], "status": "approved"}
            
        if row["status"] != "pending":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Status bukan pending")
            
        kode_prodi = row.get("kode_prodi")
        if not kode_prodi or len(str(kode_prodi)) != 3:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Kode program studi tidak valid")

        tahun = datetime.utcnow().year
        nim = self.generate_nim(tahun, kode_prodi)
        approved_at = datetime.utcnow().isoformat()
        
        self.repo.update_status_and_nim(pendaftar_id, "approved", nim, approved_at)
        updated_row = self.repo.find_pendaftar_by_id(pendaftar_id)
        return updated_row if updated_row else {"id": pendaftar_id, "message": "Disetujui dan NIM digenerate", "nim": nim, "status": "approved"}

    def get_dashboard_stats(self) -> dict:
        stats_map = self.repo.get_stats_by_status()
        pending = stats_map.get("pending", 0)
        approved = stats_map.get("approved", 0)
        rejected = stats_map.get("rejected", 0)
        total = sum(stats_map.values())
        return {
            "total_pendaftar": total,
            "pending": pending,
            "approved": approved,
            "rejected": rejected
        }
