from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import time
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.course import Course, Kelas, Schedule
from app.models.enrollment import Enrollment
from app.models.grade import Grade
from app.models.pendaftaran import PendaftaranKRS

# Pemetaan bobot numerik standar untuk mencegah jebakan perbandingan string ASCII ('D' > 'C')
GRADE_WEIGHT_MAP: dict[str, float] = {
    "A": 4.0,
    "A-": 3.7,
    "AB": 3.5,
    "B+": 3.3,
    "B": 3.0,
    "B-": 2.7,
    "BC": 2.5,
    "C+": 2.3,
    "C": 2.0,
    "D": 1.0,
    "E": 0.0,
}

MIN_PASSING_WEIGHT: float = 2.0  # Minimal C (bobot >= 2.0)
MAX_SKS_PER_SEMESTER: int = 24


@dataclass
class ValidationResult:
    """Hasil validasi dari setiap node pada Chain of Responsibility."""
    passed: bool
    message: str = "Validasi berhasil"

    @property
    def is_valid(self) -> bool:
        return self.passed


@dataclass
class ScheduleSlot:
    """Representasi jadwal terstruktur untuk pengecekan irisan interval."""
    hari: str
    jam_mulai: time
    jam_selesai: time
    ruangan: str = ""


@dataclass
class SelectedClassItem:
    """Data kelas & mata kuliah yang dipilih dalam satu pengajuan KRS."""
    id_kelas: str
    kode_mk: str
    nama_mk: str
    sks: int
    prasyarat: list[tuple[str, str]] = field(default_factory=list)  # list of (kode_prasyarat, nama_prasyarat)
    schedules: list[ScheduleSlot] = field(default_factory=list)


@dataclass
class CompletedCourseRecord:
    """Rekam jejak mata kuliah yang pernah diambil mahasiswa beserta semester dan nilainya."""
    kode_mk: str
    nama_mk: str
    semester: str
    nilai_huruf: str | None = None
    bobot: float | None = None
    krs_status: str = "Approved"


@dataclass
class KRSValidationContext:
    """Konteks data yang sudah di-load di awal (bebas query N+1 di dalam loop validator)."""
    mahasiswa_id: str
    semester_aktif: str
    selected_classes: list[SelectedClassItem]
    completed_courses: list[CompletedCourseRecord] = field(default_factory=list)


def parse_time_str(t_str: str) -> time:
    """Mengubah string 'HH:MM' menjadi objek datetime.time."""
    clean = t_str.strip()
    parts = clean.split(":")
    return time(int(parts[0]), int(parts[1]))


def extract_schedule_interval(sched: Schedule) -> tuple[time, time]:
    """Mengekstrak (jam_mulai, jam_selesai) dari model Schedule."""
    if sched.jam_mulai and sched.jam_selesai:
        return parse_time_str(sched.jam_mulai), parse_time_str(sched.jam_selesai)
    if "-" in sched.jam:
        start_s, end_s = sched.jam.split("-", 1)
        return parse_time_str(start_s), parse_time_str(end_s)
    raise ValueError(f"Format jam jadwal tidak valid: {sched.jam}")


def resolve_grade_weight(bobot: float | None, nilai_huruf: str | None) -> float:
    """Menentukan bobot numerik kelulusan tanpa membandingkan string huruf secara alfabetis/ASCII."""
    if bobot is not None:
        return float(bobot)
    if nilai_huruf is not None:
        return GRADE_WEIGHT_MAP.get(nilai_huruf.strip().upper(), 0.0)
    return 0.0


class Validator(ABC):
    """Abstract base class untuk Chain of Responsibility validasi KRS."""

    def __init__(self) -> None:
        self._next_validator: Validator | None = None

    def set_next(self, validator: Validator) -> Validator:
        self._next_validator = validator
        return validator

    def validate(self, context: KRSValidationContext) -> ValidationResult:
        result = self._check(context)
        if not result.passed:
            # Chain langsung berhenti saat ada failure
            return result
        if self._next_validator is not None:
            return self._next_validator.validate(context)
        return ValidationResult(passed=True, message="Seluruh validasi KRS berhasil")

    @abstractmethod
    def _check(self, context: KRSValidationContext) -> ValidationResult:
        pass


class SKSValidator(Validator):
    """1. SKSValidator: Cek total SKS <= 24 (tepat 24 SKS masih diizinkan)."""

    def _check(self, context: KRSValidationContext) -> ValidationResult:
        total_sks = sum(item.sks for item in context.selected_classes)
        if total_sks > MAX_SKS_PER_SEMESTER:
            daftar_mk = ", ".join(f"{item.nama_mk} ({item.sks} SKS)" for item in context.selected_classes)
            return ValidationResult(
                passed=False,
                message=f"Total SKS ({total_sks} SKS) melebihi batas maksimal {MAX_SKS_PER_SEMESTER} SKS untuk mata kuliah: {daftar_mk}"
            )
        return ValidationResult(passed=True, message=f"Total SKS valid ({total_sks} SKS)")


class DuplicateValidator(Validator):
    """4. DuplicateValidator: Cek double enrollment (MK yang sama tidak boleh diambil dua kali dalam satu KRS)."""

    def _check(self, context: KRSValidationContext) -> ValidationResult:
        seen_courses: dict[str, str] = {}
        for item in context.selected_classes:
            if item.kode_mk in seen_courses:
                return ValidationResult(
                    passed=False,
                    message=f"Double enrollment terdeteksi: mata kuliah {item.nama_mk} ({item.kode_mk}) dipilih lebih dari satu kali dalam satu KRS"
                )
            seen_courses[item.kode_mk] = item.nama_mk
        return ValidationResult(passed=True, message="Tidak ada duplikasi mata kuliah")


class PrerequisiteValidator(Validator):
    """2. PrerequisiteValidator: Cek nilai MK prasyarat >= C (bobot >= 2.0) pada semester sebelumnya."""

    def _check(self, context: KRSValidationContext) -> ValidationResult:
        # Kumpulkan mata kuliah yang sudah LULUS (bobot >= 2.0) pada SEMESTER SEBELUMNYA
        passed_prereq_codes: set[str] = set()
        for rec in context.completed_courses:
            is_previous_semester = rec.semester < context.semester_aktif
            is_krs_approved = rec.krs_status.lower() in {"approved", "disetujui", "active", "lunas"}
            weight = resolve_grade_weight(rec.bobot, rec.nilai_huruf)
            if is_previous_semester and is_krs_approved and weight >= MIN_PASSING_WEIGHT:
                passed_prereq_codes.add(rec.kode_mk)

        for item in context.selected_classes:
            for prereq_kode, prereq_nama in item.prasyarat:
                if prereq_kode not in passed_prereq_codes:
                    return ValidationResult(
                        passed=False,
                        message=(
                            f"Prasyarat belum terpenuhi untuk mata kuliah {item.nama_mk} ({item.kode_mk}): "
                            f"wajib lulus mata kuliah prasyarat {prereq_nama} ({prereq_kode}) minimal C pada semester sebelumnya"
                        ),
                    )
        return ValidationResult(passed=True, message="Seluruh prasyarat mata kuliah terpenuhi")


class ConflictValidator(Validator):
    """3. ConflictValidator: Cek bentrok jadwal menggunakan rumus irisan interval (mulai_A < selesai_B dan mulai_B < selesai_A)."""

    def _check(self, context: KRSValidationContext) -> ValidationResult:
        n = len(context.selected_classes)
        for i in range(n):
            item_a = context.selected_classes[i]
            for j in range(i + 1, n):
                item_b = context.selected_classes[j]
                for sched_a in item_a.schedules:
                    for sched_b in item_b.schedules:
                        if sched_a.hari.strip().lower() == sched_b.hari.strip().lower():
                            # Rumus irisan interval: dua rentang waktu [start_a, end_a) dan [start_b, end_b) bertumpuk
                            # jika dan hanya jika start_a < end_b DAN start_b < end_a
                            if sched_a.jam_mulai < sched_b.jam_selesai and sched_b.jam_mulai < sched_a.jam_selesai:
                                return ValidationResult(
                                    passed=False,
                                    message=(
                                        f"Jadwal bentrok pada hari {sched_a.hari} antara mata kuliah "
                                        f"{item_a.nama_mk} ({sched_a.jam_mulai.strftime('%H:%M')}-{sched_a.jam_selesai.strftime('%H:%M')}) "
                                        f"dan {item_b.nama_mk} ({sched_b.jam_mulai.strftime('%H:%M')}-{sched_b.jam_selesai.strftime('%H:%M')})"
                                    ),
                                )
        return ValidationResult(passed=True, message="Tidak ada jadwal kuliah yang bentrok")


def build_krs_validation_chain() -> Validator:
    """Merangkai keempat validator sesuai urutan Chain of Responsibility."""
    sks_validator = SKSValidator()
    duplicate_validator = DuplicateValidator()
    prerequisite_validator = PrerequisiteValidator()
    conflict_validator = ConflictValidator()

    sks_validator.set_next(duplicate_validator).set_next(prerequisite_validator).set_next(conflict_validator)
    return sks_validator


def validate_krs_with_db(
    db: Session,
    mahasiswa_id: str,
    kelas_ids: list[str],
    semester_aktif: str,
) -> ValidationResult:
    """Menjalankan validasi KRS menggunakan SQLAlchemy 2.0 dengan eager loading (bebas query N+1 di dalam loop)."""
    # 1. Batch query seluruh kelas yang dipilih beserta Course, Prasyarat, dan Schedules dalam 1 rangkaian query
    stmt_kelas = (
        select(Kelas)
        .where(Kelas.id_kelas.in_(kelas_ids))
        .options(
            selectinload(Kelas.course).selectinload(Course.prasyarat),
            selectinload(Kelas.schedules),
        )
    )
    kelas_map = {k.id_kelas: k for k in db.scalars(stmt_kelas).all()}

    selected_items: list[SelectedClassItem] = []
    for kid in kelas_ids:
        k_obj = kelas_map.get(kid)
        if k_obj is None:
            return ValidationResult(passed=False, message=f"Kelas dengan ID {kid} tidak ditemukan")
        course_obj = k_obj.course
        prereqs = [(p.kode, p.nama) for p in course_obj.prasyarat]
        slots = []
        for s in k_obj.schedules:
            start_t, end_t = extract_schedule_interval(s)
            slots.append(ScheduleSlot(hari=s.hari, jam_mulai=start_t, jam_selesai=end_t, ruangan=s.ruangan))
        selected_items.append(
            SelectedClassItem(
                id_kelas=k_obj.id_kelas,
                kode_mk=course_obj.kode,
                nama_mk=course_obj.nama,
                sks=course_obj.sks,
                prasyarat=prereqs,
                schedules=slots,
            )
        )

    # 2. Batch query riwayat Enrollment mahasiswa beserta Grade, Kelas->Course, dan PendaftaranKRS (tanpa N+1)
    stmt_history = (
        select(Enrollment)
        .where(Enrollment.mahasiswa_id == mahasiswa_id)
        .options(
            selectinload(Enrollment.grade),
            selectinload(Enrollment.pendaftaran_krs),
            selectinload(Enrollment.kelas).selectinload(Kelas.course),
        )
    )
    history_enrollments = db.scalars(stmt_history).all()

    completed_records: list[CompletedCourseRecord] = []
    for enr in history_enrollments:
        if enr.kelas and enr.kelas.course:
            sem = enr.pendaftaran_krs.semester if enr.pendaftaran_krs else enr.kelas.semester
            status_krs = enr.pendaftaran_krs.status if enr.pendaftaran_krs else "Approved"
            completed_records.append(
                CompletedCourseRecord(
                    kode_mk=enr.kelas.course.kode,
                    nama_mk=enr.kelas.course.nama,
                    semester=sem,
                    nilai_huruf=enr.grade.nilaiHuruf if enr.grade else None,
                    bobot=enr.grade.bobot if enr.grade else None,
                    krs_status=status_krs,
                )
            )

    context = KRSValidationContext(
        mahasiswa_id=mahasiswa_id,
        semester_aktif=semester_aktif,
        selected_classes=selected_items,
        completed_courses=completed_records,
    )

    chain = build_krs_validation_chain()
    return chain.validate(context)
