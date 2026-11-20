from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import time
from decimal import Decimal
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session, selectinload

from app.models.course import Course, Kelas, Schedule
from app.models.enrollment import Enrollment
from app.models.finance import Billing, BillingStatus
from app.models.grade import SkalaNilai
from app.models.krs import KRS, KRSDetail, KRSStatus, MataKuliah, prerequisite
from app.models.pendaftaran import PendaftaranKRS
from app.services.finance_calculator import ZERO, format_rupiah, quantize_money, to_decimal

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
MAX_SKS: int = 24
MAX_SKS_PER_SEMESTER: int = MAX_SKS


@dataclass(frozen=True)
class ValidationResult:
    """Hasil validasi dari setiap node pada Chain of Responsibility (Slide 7)."""
    ok: bool = True
    message: str = ""

    def __init__(self, ok: bool | None = None, message: str = "", *, passed: bool | None = None) -> None:
        resolved_ok = passed if passed is not None else (True if ok is None else bool(ok))
        object.__setattr__(self, "ok", resolved_ok)
        object.__setattr__(self, "message", message)

    @property
    def passed(self) -> bool:
        return self.ok

    @property
    def is_valid(self) -> bool:
        return self.ok


@dataclass
class KRSContext:
    """Konteks validasi saat menambahkan mata kuliah baru ke kartu KRS (Slide 7)."""
    nim: str
    semester: str
    details: list[KRSDetail]  # MK lain yang sudah ada di KRS
    mk_baru: MataKuliah
    db: Session | None = None
    kelas_baru: Any = None


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
    prasyarat: list[tuple[str, str]] = field(default_factory=list)
    schedules: list[ScheduleSlot] = field(default_factory=list)


@dataclass
class CompletedCourseRecord:
    """Rekam jejak mata kuliah yang pernah diambil mahasiswa beserta semester dan nilainya."""
    kode_mk: str
    nama_mk: str
    semester: str
    nilai_huruf: str | None = None
    bobot: float | None = None
    krs_status: str = "APPROVED"


@dataclass
class KRSValidationContext:
    """Konteks batch in-memory (mendukung pengujian tanpa DB maupun dengan DB)."""
    mahasiswa_id: str
    semester_aktif: str
    selected_classes: list[SelectedClassItem]
    completed_courses: list[CompletedCourseRecord] = field(default_factory=list)


def resolve_grade_weight(bobot: float | None, nilai_huruf: str | None) -> float:
    """Menentukan bobot numerik kelulusan tanpa membandingkan string huruf secara alfabetis/ASCII."""
    if bobot is not None:
        return float(bobot)
    if nilai_huruf is not None:
        return GRADE_WEIGHT_MAP.get(nilai_huruf.strip().upper(), 0.0)
    return 0.0


def prasyarat_belum_lulus(
    db: Session | None,
    nim: str,
    kode_mk: str,
    semester: str,
    mk_obj: MataKuliah | None = None,
) -> list[str]:
    """Mencari daftar nama mata kuliah prasyarat yang belum lulus (nilai < C) di semester sebelumnya (Slide 8).
    Menggunakan query terpusat (bebas N+1 query di dalam loop).
    """
    if db is None:
        return []

    target_mk = mk_obj
    if target_mk is None:
        stmt_mk = (
            select(MataKuliah)
            .where(MataKuliah.kode_mk == kode_mk)
            .options(selectinload(MataKuliah.prasyarat))
        )
        target_mk = db.scalars(stmt_mk).first()

    if target_mk is None or not target_mk.prasyarat:
        return []

    prereq_list = list(target_mk.prasyarat)
    prereq_codes = [p.kode_mk for p in prereq_list]

    # Ambil seluruh riwayat KRSDetail mahasiswa pada semester sebelumnya (< semester saat ini)
    # yang kartu KRS-nya sudah APPROVED dalam satu kali query (bebas N+1).
    # Jika tabel skala_nilai terisi, baca kelulusan langsung dari kolom `lulus` (data-driven).
    has_skala = db.scalars(select(SkalaNilai.huruf).limit(1)).first() is not None
    lulus_codes: set[str] = set()
    if has_skala:
        stmt_passed = (
            select(KRSDetail.kode_mk)
            .join(KRS, KRSDetail.krs_id == KRS.id)
            .join(SkalaNilai, KRSDetail.nilai == SkalaNilai.huruf)
            .where(
                KRS.nim == nim,
                KRS.semester < semester,
                KRS.status == KRSStatus.APPROVED,
                KRSDetail.kode_mk.in_(prereq_codes),
                SkalaNilai.lulus.is_(True),
            )
        )
        lulus_codes = set(db.scalars(stmt_passed).all())
    else:
        stmt_passed = (
            select(KRSDetail.kode_mk, KRSDetail.nilai)
            .join(KRS, KRSDetail.krs_id == KRS.id)
            .where(
                KRS.nim == nim,
                KRS.semester < semester,
                KRS.status == KRSStatus.APPROVED,
                KRSDetail.kode_mk.in_(prereq_codes),
                KRSDetail.nilai.is_not(None),
            )
        )
        rows = db.execute(stmt_passed).all()
        for r_kode, r_nilai in rows:
            if resolve_grade_weight(None, r_nilai) >= MIN_PASSING_WEIGHT:
                lulus_codes.add(r_kode)

    kurang = [p.nama for p in prereq_list if p.kode_mk not in lulus_codes]
    return kurang


class Validator(ABC):
    """Abstract base class untuk Chain of Responsibility validasi KRS (Slide 7)."""
    _next: Validator | None = None

    def __init__(self) -> None:
        self._next = None

    def set_next(self, nxt: Validator) -> Validator:
        self._next = nxt
        return nxt

    def validate(self, ctx: KRSContext | KRSValidationContext) -> ValidationResult:
        hasil = self.check(ctx)
        if not hasil.ok or self._next is None:
            return hasil  # berhenti di kegagalan pertama
        return self._next.validate(ctx)

    @abstractmethod
    def check(self, ctx: KRSContext | KRSValidationContext) -> ValidationResult: ...


class DuplicateValidator(Validator):
    """Pos 1 — DuplicateValidator: Cek apakah mata kuliah sudah ada di KRS (Slide 8)."""

    def check(self, ctx: KRSContext | KRSValidationContext) -> ValidationResult:
        if isinstance(ctx, KRSContext):
            if any(d.kode_mk == ctx.mk_baru.kode_mk for d in ctx.details):
                return ValidationResult(False, f"Sudah ada di KRS: {ctx.mk_baru.nama}")
            return ValidationResult(True)

        seen_courses: dict[str, str] = {}
        for item in ctx.selected_classes:
            if item.kode_mk in seen_courses:
                return ValidationResult(
                    False,
                    f"Sudah ada di KRS: {item.nama_mk} ({item.kode_mk})",
                )
            seen_courses[item.kode_mk] = item.nama_mk
        return ValidationResult(True)


class SKSValidator(Validator):
    """Pos 2 — SKSValidator: Cek apakah total SKS <= 24 (tepat 24 SKS masih diizinkan) (Slide 8)."""

    def check(self, ctx: KRSContext | KRSValidationContext) -> ValidationResult:
        if isinstance(ctx, KRSContext):
            total = sum(d.matakuliah.sks for d in ctx.details) + ctx.mk_baru.sks
            if total > MAX_SKS:
                return ValidationResult(
                    False,
                    f"Total SKS {total} melebihi batas {MAX_SKS} saat menambah {ctx.mk_baru.nama}",
                )
            return ValidationResult(True)

        total_sks = sum(item.sks for item in ctx.selected_classes)
        if total_sks > MAX_SKS:
            daftar_mk = ", ".join(f"{item.nama_mk} ({item.sks} SKS)" for item in ctx.selected_classes)
            return ValidationResult(
                False,
                f"Total SKS ({total_sks} SKS) melebihi batas {MAX_SKS} SKS untuk mata kuliah: {daftar_mk}",
            )
        return ValidationResult(True)


class PrerequisiteValidator(Validator):
    """Pos 3 — PrerequisiteValidator: Cek kelulusan MK prasyarat >= C di semester sebelumnya (Slide 8)."""

    def check(self, ctx: KRSContext | KRSValidationContext) -> ValidationResult:
        if isinstance(ctx, KRSContext):
            kurang = prasyarat_belum_lulus(
                ctx.db, ctx.nim, ctx.mk_baru.kode_mk, ctx.semester, mk_obj=ctx.mk_baru
            )
            if kurang:
                return ValidationResult(
                    False,
                    f"Prasyarat tidak terpenuhi: {', '.join(kurang)} (untuk {ctx.mk_baru.nama})",
                )
            return ValidationResult(True)

        passed_prereq_codes: set[str] = set()
        for rec in ctx.completed_courses:
            is_previous_semester = rec.semester < ctx.semester_aktif
            is_krs_approved = rec.krs_status.lower() in {"approved", "disetujui", "active", "lunas"}
            weight = resolve_grade_weight(rec.bobot, rec.nilai_huruf)
            if is_previous_semester and is_krs_approved and weight >= MIN_PASSING_WEIGHT:
                passed_prereq_codes.add(rec.kode_mk)

        for item in ctx.selected_classes:
            kurang_nama = [
                prereq_nama
                for prereq_kode, prereq_nama in item.prasyarat
                if prereq_kode not in passed_prereq_codes
            ]
            if kurang_nama:
                return ValidationResult(
                    False,
                    f"Prasyarat tidak terpenuhi: {', '.join(kurang_nama)} (untuk {item.nama_mk})",
                )
        return ValidationResult(True)


class ConflictValidator(Validator):
    """Pos 4 — ConflictValidator: Cek bentrok jadwal dengan rumus irisan interval (mulai_A < selesai_B dan mulai_B < selesai_A)."""

    def check(self, ctx: KRSContext | KRSValidationContext) -> ValidationResult:
        if isinstance(ctx, KRSContext):
            mk_b = ctx.mk_baru
            if ctx.kelas_baru is not None and getattr(ctx.kelas_baru, "jadwals", None):
                slots_b = [
                    (j.hari, j.jam_mulai, j.jam_selesai) for j in ctx.kelas_baru.jadwals
                ]
            else:
                slots_b = mk_b.get_jadwal_slots()

            for d in ctx.details:
                mk_a = d.matakuliah
                if getattr(d, "kelas", None) is not None and getattr(d.kelas, "jadwals", None):
                    slots_a = [
                        (j.hari, j.jam_mulai, j.jam_selesai) for j in d.kelas.jadwals
                    ]
                else:
                    slots_a = mk_a.get_jadwal_slots()

                for hari_a, mulai_a, selesai_a in slots_a:
                    for hari_b, mulai_b, selesai_b in slots_b:
                        if hari_a == hari_b:
                            # Rumus irisan interval: start_a < end_b DAN start_b < end_a
                            if mulai_a < selesai_b and mulai_b < selesai_a:
                                return ValidationResult(
                                    False,
                                    f"Jadwal bentrok: {mk_b.nama} bertabrakan dengan {mk_a.nama}",
                                )
            return ValidationResult(True)

        n = len(ctx.selected_classes)
        for i in range(n):
            item_a = ctx.selected_classes[i]
            for j in range(i + 1, n):
                item_b = ctx.selected_classes[j]
                for sched_a in item_a.schedules:
                    for sched_b in item_b.schedules:
                        if str(sched_a.hari).strip().lower() == str(sched_b.hari).strip().lower():
                            if sched_a.jam_mulai < sched_b.jam_selesai and sched_b.jam_mulai < sched_a.jam_selesai:
                                return ValidationResult(
                                    False,
                                    (
                                        f"Jadwal bentrok pada hari {sched_a.hari} antara mata kuliah "
                                        f"{item_a.nama_mk} dan {item_b.nama_mk}"
                                    ),
                                )
        return ValidationResult(True)


class TunggakanValidator(Validator):
    """Validator opsional pemblokir KRS apabila mahasiswa memiliki tagihan SPP belum lunas."""

    def check(self, ctx: KRSContext | KRSValidationContext) -> ValidationResult:
        if not isinstance(ctx, KRSContext) or ctx.db is None:
            return ValidationResult(True)
        conn = ctx.db.connection()
        if not inspect(conn).has_table(Billing.__tablename__):
            return ValidationResult(True)

        stmt = (
            select(Billing)
            .where(Billing.nim == ctx.nim, Billing.status != BillingStatus.PAID)
            .order_by(Billing.due_date.asc(), Billing.id.asc())
        )
        unpaid = list(ctx.db.scalars(stmt).all())
        if not unpaid:
            return ValidationResult(True)

        total_sisa = sum(
            (quantize_money(to_decimal(b.remaining)) for b in unpaid),
            start=ZERO,
        )
        statuses = ", ".join(sorted({b.status.value for b in unpaid}))
        return ValidationResult(
            False,
            f"Pengisian KRS diblokir karena masih ada {len(unpaid)} tagihan SPP "
            f"belum lunas ({statuses}) sebesar {format_rupiah(total_sisa)}",
        )


def build_chain(vs: list[Validator]) -> Validator:
    """Merangkai daftar validator menjadi Chain of Responsibility (Slide 7)."""
    for a, b in zip(vs, vs[1:]):
        a.set_next(b)
    return vs[0]


def default_validators() -> list[Validator]:
    """Urutan standar sesuai Slide 6 & 8: Duplicate -> SKS -> Prerequisite -> Conflict
    (paling murah & pesan paling tepat di depan).
    """
    return [
        DuplicateValidator(),
        SKSValidator(),
        PrerequisiteValidator(),
        ConflictValidator(),
    ]


def build_krs_validation_chain() -> Validator:
    """Helper pembangun rantai validator dengan urutan Duplicate -> SKS -> Prerequisite -> Conflict."""
    return build_chain(default_validators())


def parse_time_str(t_str: str) -> time:
    clean = t_str.strip()
    parts = clean.split(":")
    return time(int(parts[0]), int(parts[1]))


def extract_schedule_interval(sched: Schedule) -> tuple[time, time]:
    if sched.jam_mulai and sched.jam_selesai:
        return parse_time_str(sched.jam_mulai), parse_time_str(sched.jam_selesai)
    if "-" in sched.jam:
        start_s, end_s = sched.jam.split("-", 1)
        return parse_time_str(start_s), parse_time_str(end_s)
    raise ValueError(f"Format jam jadwal tidak valid: {sched.jam}")


def validate_krs_with_db(
    db: Session,
    mahasiswa_id: str,
    kelas_ids: list[str],
    semester_aktif: str,
) -> ValidationResult:
    """Validasi batch dengan eager loading (bebas query N+1)."""
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
            return ValidationResult(False, f"Kelas dengan ID {kid} tidak ditemukan")
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
