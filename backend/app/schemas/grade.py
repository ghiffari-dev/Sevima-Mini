from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class GradeCreate(BaseModel):
    enrollment_id: str
    nilaiAngka: float = Field(..., ge=0.0, le=100.0)


class GradeResponse(BaseModel):
    nilaiAngka: float
    nilaiHuruf: str
    bobot: float

    model_config = ConfigDict(from_attributes=True)


class KHSResponse(BaseModel):
    mahasiswa_id: str
    semester: str
    grades: list[dict]
    ips: float
    total_sks: int


class NilaiIn(BaseModel):
    """Payload input/edit nilai oleh dosen pengampu (huruf tunggal A..E)."""

    huruf: str = Field(..., min_length=1, max_length=1, pattern=r"^[A-E]$")
    alasan: str | None = Field(default=None, max_length=500)


class NilaiOut(BaseModel):
    """Respons hasil input/edit nilai beserta IPK & IPS terbaru dalam format string 2 desimal."""

    nim: str
    kelas_id: int
    semester: str
    nilai_lama: str | None = None
    nilai_baru: str
    changed: bool
    presensi_persen: str
    ips: str
    ipk: str
    history_id: int | None = None
    detail: str


class IPSResponse(BaseModel):
    """Respons perhitungan IPS satu semester (string 2 desimal agar tidak terkonversi ke float)."""

    nim: str
    semester: str
    ips: str


class IPKResponse(BaseModel):
    """Respons perhitungan IPK kumulatif compute-on-read (string 2 desimal)."""

    nim: str
    ipk: str


class GradeHistoryItem(BaseModel):
    """Satu baris audit trail dari SQL View `riwayat_nilai`."""

    id: int
    grade_id: int
    nim: str
    semester: str
    kode_mk: str
    nama_mk: str
    kelas_id: int | None = None
    nilai_lama: str | None = None
    nilai_baru: str
    diubah_oleh: int
    nama_dosen: str
    diubah_pada: str
    alasan: str | None = None


class KelasPesertaItem(BaseModel):
    """Status peserta kelas beserta persentase presensi & kelayakan input nilai."""

    nim: str
    nama: str
    semester: str
    nilai: str | None = None
    presensi_persen: str
    bisa_diinput: bool
    alasan_blokir: str | None = None


class KelasPesertaResponse(BaseModel):
    """Daftar peserta suatu kelas beserta metadata mata kuliah."""

    kelas_id: int
    kode_mk: str
    nama_mk: str
    nama_kelas: str
    sks: int
    semester: str
    peserta: list[KelasPesertaItem]


class KelasPengampuItem(BaseModel):
    """Ringkasan kelas yang diampu oleh dosen terautentikasi."""

    kelas_id: int
    kode_mk: str
    nama_mk: str
    nama_kelas: str
    sks: int
    semester: str
    jumlah_peserta: int
