from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, Field


class OpenSessionRequest(BaseModel):
    """Payload pembukaan sesi presensi oleh dosen untuk jadwal kuliah tertentu."""

    schedule_id: int = Field(..., ge=1)
    tanggal: date | None = None
    pertemuan_ke: int | None = Field(default=None, ge=1, le=32)
    valid_minutes: int = Field(default=30, ge=1, le=240)
    latitude: float | None = Field(default=None, ge=-90.0, le=90.0)
    longitude: float | None = Field(default=None, ge=-180.0, le=180.0)
    radius_m: int | None = Field(default=None, ge=10, le=5000)


class QRSessionInfoResponse(BaseModel):
    """Respons metadata sesi presensi & token QR berotasi aktif."""

    session_id: int
    schedule_id: int | None
    kelas_id: int
    kode_mk: str
    nama_mk: str
    nama_kelas: str
    semester: str
    tanggal: str
    pertemuan_ke: int
    hari: int
    hari_nama: str
    jam_mulai: str
    jam_selesai: str
    ruangan_kode: str | None
    status: str
    token: str
    qr_window: int
    rotate_seconds: int
    grace_windows: int
    window_expires_at: str
    session_opened_at: str
    session_closes_at: str
    seconds_until_rotation: int
    geofence_enabled: bool
    latitude: float | None = None
    longitude: float | None = None
    radius_m: int | None = None
    qr_image_url: str


class AttendanceScanRequest(BaseModel):
    """Payload scan QR presensi oleh mahasiswa (Step 2 spesifikasi + koordinat GPS opsional)."""

    token: str = Field(..., min_length=10)
    nim: str | None = Field(default=None, min_length=2, max_length=30)
    latitude: float | None = Field(default=None, ge=-90.0, le=90.0)
    longitude: float | None = Field(default=None, ge=-180.0, le=180.0)
    accuracy_m: float | None = Field(default=None, ge=0.0, le=10000.0)


class AttendanceScanResponse(BaseModel):
    """Respons hasil scan QR presensi (`{success: true, status: 'hadir'|'terlambat', message: '...'}`)."""

    success: bool = True
    status: str
    message: str
    record_id: int
    session_id: int
    schedule_id: int | None = None
    kelas_id: int
    kode_mk: str
    nama_mk: str
    nim: str
    pertemuan_ke: int
    scanned_at: str
    qr_window: int
    distance_m: float | None = None


class StudentCourseAttendanceItem(BaseModel):
    """Rekap presensi seorang mahasiswa pada satu mata kuliah / kelas."""

    kelas_id: int
    kode_mk: str
    nama_mk: str
    nama_kelas: str
    semester: str
    total_pertemuan: int
    hadir: int
    terlambat: int
    alpha: int
    persentase_kehadiran: str
    memenuhi_syarat: bool
    warning_dibawah_75: bool
    risk_level: str


class StudentAttendanceReportResponse(BaseModel):
    """Laporan presensi per mahasiswa untuk seluruh mata kuliah yang diikuti."""

    nim: str
    nama: str
    total_mk: int
    jumlah_warning_dibawah_75: int
    courses: list[StudentCourseAttendanceItem]


class ClassStudentAttendanceItem(BaseModel):
    """Baris rekap presensi mahasiswa di dalam satu kelas perkuliahan."""

    nim: str
    nama: str
    total_pertemuan: int
    hadir: int
    terlambat: int
    alpha: int
    persentase_kehadiran: str
    memenuhi_syarat: bool
    warning_dibawah_75: bool
    risk_level: str


class ClassAttendanceReportResponse(BaseModel):
    """Laporan presensi per mata kuliah / kelas beserta daftar warning < 75%."""

    kelas_id: int
    kode_mk: str
    nama_mk: str
    nama_kelas: str
    semester: str
    total_sesi_dibuka: int
    rata_rata_kehadiran: str
    jumlah_mahasiswa: int
    jumlah_warning_dibawah_75: int
    peserta: list[ClassStudentAttendanceItem]
    mahasiswa_warning: list[ClassStudentAttendanceItem]


class AIAttendanceRecordItem(BaseModel):
    """Satu baris data presensi untuk dianalisis oleh AI Attendance Analyzer (Step 3)."""

    nim: str = Field(..., min_length=2, max_length=30)
    nama: str | None = None
    kelas: str | None = None
    kode_mk: str | None = None
    hari: int | str | None = None
    jam: str | None = None
    pertemuan_ke: int | None = None
    tanggal: str | None = None
    status: str = Field(..., description="hadir | terlambat | alpha | absent")


class AIAttendanceAnalyzeRequest(BaseModel):
    """Input JSON array `attendance_records` untuk Step 3 AI Attendance Analyzer."""

    attendance_records: list[AIAttendanceRecordItem] = Field(..., min_length=1)


class AIAttendanceAnalyzeResponse(BaseModel):
    """Output terstruktur AI Attendance Analyzer dengan insights + actions."""

    ai_source: str
    early_warning: str
    total_mahasiswa: int
    jumlah_mahasiswa_berisiko: int
    student_attendance: list[dict[str, Any]]
    warning_under_75: list[dict[str, Any]]
    detected_patterns: list[dict[str, Any]]
    insights: list[str]
    actions: list[str]
    recommendations: list[str]
