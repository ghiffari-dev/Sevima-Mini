from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List

class IPMBRepository(ABC):
    @abstractmethod
    def find_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        pass

    @abstractmethod
    def find_prodi_by_id(self, prodi_id: int) -> Optional[Dict[str, Any]]:
        pass

    @abstractmethod
    def find_jalur_by_id(self, jalur_id: int) -> Optional[Dict[str, Any]]:
        pass

    @abstractmethod
    def save_calon_mahasiswa(self, data_dict: Dict[str, Any]) -> int:
        pass

    @abstractmethod
    def find_pendaftar_by_id(self, pendaftar_id: int) -> Optional[Dict[str, Any]]:
        pass

    @abstractmethod
    def update_status_and_nim(self, pendaftar_id: int, status: str, nim: Optional[str], approved_at: Optional[str]) -> None:
        pass

    @abstractmethod
    def get_latest_nim_by_prefix(self, prefix: str) -> Optional[str]:
        pass

    @abstractmethod
    def get_stats_by_status(self) -> Dict[str, int]:
        pass
