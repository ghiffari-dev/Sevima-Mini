from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.calon_mahasiswa import CalonMahasiswa
from app.models.jalur_masuk import JalurMasuk
from app.models.krs import (
    KRS,
    KRSDetail,
    KRSLog,
    KRSStatus,
    MataKuliah,
    Notifikasi,
)
from app.models.program_studi import ProgramStudi
from app.models.schedule import (
    HARI_MAP,
    JadwalKuliah,
    Ruangan,
    ScheduleError,
    ScheduleNotFoundError,
    ScheduleConflictError,
    normalize_hari,
)
from app.services.conflict_detector import (
    ScheduleRecord,
    check_room_capacity,
    detect_schedule_conflict,
    record_to_dict,
)
from app.services.schedule_observer import (
    NotificationManager,
    default_notification_manager,
)
from app.services.schedule_recommender import suggest_alternative_schedules


def _coerce_time(value: time | str) -> time:
    if isinstance(value, time):
        return value
    parts = str(value).strip().split(":")
    if len(parts) < 2:
        raise ScheduleError(f"Format jam tidak valid: {value}")
    try:
        return time(int(parts[0]), int(parts[1]))
    except ValueError as exc:
        raise ScheduleError(f"Format jam tidak valid: {value}") from exc


class SchedulingService:
    """Layanan terpadu penjadwalan, deteksi bentrok 3D, notifikasi Observer, & invalidasi KRS."""

    def __init__(
        self,
        db: Session,
        notification_manager: NotificationManager | None = None,
    ) -> None:
        self.db = db
        self.notification_manager = notification_manager or default_notification_manager

    # ------------------------------------------------------------------
    # Manajemen Ruangan
    # ------------------------------------------------------------------

    def list_rooms(self) -> list[Ruangan]:
        stmt = select(Ruangan).order_by(Ruangan.kode_ruangan.asc())
        return list(self.db.scalars(stmt).all())

    def get_room(self, kode_ruangan: str) -> Ruangan:
        room = self.db.get(Ruangan, kode_ruangan)
        if room is None:
            raise ScheduleNotFoundError(f"Ruangan {kode_ruangan} tidak ditemukan")
        return room

    def create_room(
        self,
        kode_ruangan: str,
        nama: str,
        kapasitas: int,
        gedung: str | None = None,
    ) -> Ruangan:
        if kapasitas <= 0:
            raise ScheduleError("Kapasitas ruangan harus lebih besar dari 0")
        existing = self.db.get(Ruangan, kode_ruangan)
        if existing is not None:
            raise ScheduleError(
                f"Ruangan {kode_ruangan} sudah terdaftar", status_code=409
            )
        room = Ruangan(
            kode_ruangan=kode_ruangan.strip(),
            nama=nama.strip(),
            kapasitas=kapasitas,
            gedung=gedung.strip() if gedung else None,
        )
        self.db.add(room)
        self.db.commit()
        self.db.refresh(room)
        return room

    # ------------------------------------------------------------------
    # Helper Internal
    # ------------------------------------------------------------------

    def _nims_by_course(
        self, semester: str, kode_mks: list[str] | None = None
    ) -> dict[str, set[str]]:
        """Mengambil daftar NIM per mata kuliah pada semester tertentu dalam 1 query."""
        stmt = (
            select(KRSDetail.kode_mk, KRS.nim)
            .join(KRS, KRSDetail.krs_id == KRS.id)
            .where(KRS.semester == semester)
        )
        if kode_mks is not None:
            if not kode_mks:
                return {}
            stmt = stmt.where(KRSDetail.kode_mk.in_(kode_mks))

        mapping: dict[str, set[str]] = defaultdict(set)
        for kode_mk, nim in self.db.execute(stmt).all():
            mapping[kode_mk].add(nim)
        return mapping

    def _effective_enrolled(
        self, kode_mk: str, semester: str, override_count: int = 0
    ) -> tuple[int, set[str]]:
        nims = self._nims_by_course(semester, [kode_mk]).get(kode_mk, set())
        return max(int(override_count), len(nims)), nims

    def _to_records(
        self, schedules: list[JadwalKuliah], semester: str
    ) -> list[ScheduleRecord]:
        kode_mks = list({j.kode_mk for j in schedules})
        nims_map = self._nims_by_course(semester, kode_mks)
        records: list[ScheduleRecord] = []
        for j in schedules:
            nims = nims_map.get(j.kode_mk, set())
            records.append(
                ScheduleRecord(
                    id=j.id,
                    kode_mk=j.kode_mk,
                    nama_mk=j.matakuliah.nama if j.matakuliah else j.kode_mk,
                    hari=j.hari,
                    jam_mulai=j.jam_mulai,
                    jam_selesai=j.jam_selesai,
                    ruangan=j.ruangan_kode,
                    dosen=j.dosen,
                    enrolled_count=max(j.enrolled_count, len(nims)),
                    kapasitas=j.ruangan.kapasitas if j.ruangan else None,
                    enrolled_nims=nims,
                )
            )
        return records

    def _sync_matakuliah_time(
        self, mk: MataKuliah, hari: int, jam_mulai: time, jam_selesai: time
    ) -> None:
        mk.hari = hari
        mk.jam_mulai = jam_mulai
        mk.jam_selesai = jam_selesai

    def _invalidate_affected_krs(
        self,
        kode_mk: str,
        semester: str,
        reason: str,
        aksi: str,
    ) -> tuple[list[int], list[str], list[str]]:
        """Mengembalikan seluruh KRS terdampak (SUBMITTED/APPROVED/REVISION) ke REVISION dalam transaksi ACID."""
        stmt = (
            select(KRS)
            .join(KRSDetail, KRSDetail.krs_id == KRS.id)
            .where(KRS.semester == semester, KRSDetail.kode_mk == kode_mk)
            .distinct()
            .with_for_update()
        )
        affected_krs = list(self.db.scalars(stmt).all())
        invalidated_ids: list[int] = []
        invalidated_nims: list[str] = []
        all_nims: list[str] = []

        for krs in affected_krs:
            all_nims.append(krs.nim)
            if krs.status in (
                KRSStatus.SUBMITTED,
                KRSStatus.APPROVED,
                KRSStatus.REVISION,
            ):
                krs.invalidate_by_schedule_change(reason=reason)
                self.db.add(KRSLog(krs_id=krs.id, aksi=aksi, oleh=None))
                self.db.add(Notifikasi(nim=krs.nim, pesan=reason))
                invalidated_ids.append(krs.id)
                invalidated_nims.append(krs.nim)
            else:
                # KRS masih DRAFT: tetap beri notifikasi tanpa mengubah status DRAFT
                self.db.add(Notifikasi(nim=krs.nim, pesan=reason))

        return invalidated_ids, invalidated_nims, all_nims

    # ------------------------------------------------------------------
    # CRUD Jadwal Kuliah
    # ------------------------------------------------------------------

    def list_schedules(self, semester: str | None = None) -> list[JadwalKuliah]:
        stmt = select(JadwalKuliah).options(
            selectinload(JadwalKuliah.matakuliah),
            selectinload(JadwalKuliah.ruangan),
        )
        if semester is not None:
            stmt = stmt.where(JadwalKuliah.semester == semester)
        stmt = stmt.order_by(JadwalKuliah.hari.asc(), JadwalKuliah.jam_mulai.asc(), JadwalKuliah.id.asc())
        return list(self.db.scalars(stmt).all())

    def get_schedule(self, schedule_id: int) -> JadwalKuliah:
        stmt = (
            select(JadwalKuliah)
            .where(JadwalKuliah.id == schedule_id)
            .options(
                selectinload(JadwalKuliah.matakuliah),
                selectinload(JadwalKuliah.ruangan),
            )
        )
        jadwal = self.db.scalars(stmt).first()
        if jadwal is None:
            raise ScheduleNotFoundError(f"Jadwal dengan ID {schedule_id} tidak ditemukan")
        return jadwal

    def schedule_to_response_dict(self, jadwal: JadwalKuliah) -> dict[str, Any]:
        eff_enrolled, _ = self._effective_enrolled(
            jadwal.kode_mk, jadwal.semester, jadwal.enrolled_count
        )
        kap = jadwal.ruangan.kapasitas if jadwal.ruangan else 0
        return {
            "id": jadwal.id,
            "kode_mk": jadwal.kode_mk,
            "nama_mk": jadwal.matakuliah.nama if jadwal.matakuliah else jadwal.kode_mk,
            "ruangan_kode": jadwal.ruangan_kode,
            "ruangan_nama": jadwal.ruangan.nama if jadwal.ruangan else jadwal.ruangan_kode,
            "kapasitas": kap,
            "dosen": jadwal.dosen,
            "semester": jadwal.semester,
            "hari": jadwal.hari,
            "hari_nama": HARI_MAP[jadwal.hari],
            "jam_mulai": jadwal.jam_mulai.strftime("%H:%M"),
            "jam_selesai": jadwal.jam_selesai.strftime("%H:%M"),
            "jam": f"{jadwal.jam_mulai.strftime('%H:%M')}-{jadwal.jam_selesai.strftime('%H:%M')}",
            "enrolled_count": eff_enrolled,
        }

    def create_schedule(
        self,
        *,
        kode_mk: str,
        ruangan_kode: str,
        dosen: str,
        hari: int | str,
        jam_mulai: time | str,
        jam_selesai: time | str,
        semester: str = "20251",
        enrolled_count: int = 0,
        force: bool = False,
    ) -> dict[str, Any]:
        mk = self.db.get(MataKuliah, kode_mk)
        if mk is None:
            raise ScheduleNotFoundError(f"Mata kuliah {kode_mk} tidak ditemukan")
        room = self.get_room(ruangan_kode)

        hari_num = normalize_hari(hari)
        mulai = _coerce_time(jam_mulai)
        selesai = _coerce_time(jam_selesai)
        if mulai >= selesai:
            raise ScheduleError("jam_mulai harus lebih awal daripada jam_selesai")
        if enrolled_count < 0:
            raise ScheduleError("enrolled_count tidak boleh negatif")

        eff_enrolled, nims = self._effective_enrolled(kode_mk, semester, enrolled_count)
        check_room_capacity(eff_enrolled, room.kapasitas, room.kode_ruangan)

        existing = self.list_schedules(semester=semester)
        existing_records = self._to_records(existing, semester)
        candidate_record = ScheduleRecord(
            id=-1,
            kode_mk=mk.kode_mk,
            nama_mk=mk.nama,
            hari=hari_num,
            jam_mulai=mulai,
            jam_selesai=selesai,
            ruangan=room.kode_ruangan,
            dosen=dosen.strip(),
            enrolled_count=eff_enrolled,
            kapasitas=room.kapasitas,
            enrolled_nims=nims,
        )
        conflicts = detect_schedule_conflict([*existing_records, candidate_record])
        relevant_conflicts = [
            c
            for c in conflicts
            if any(s.get("id") == -1 for s in c["affected_schedules"])
        ]
        if relevant_conflicts and not force:
            raise ScheduleConflictError(
                relevant_conflicts[0]["detail"],
                conflicts=relevant_conflicts,
            )

        now = datetime.now(timezone.utc)
        jadwal = JadwalKuliah(
            kode_mk=mk.kode_mk,
            ruangan_kode=room.kode_ruangan,
            dosen=dosen.strip(),
            semester=semester,
            hari=hari_num,
            jam_mulai=mulai,
            jam_selesai=selesai,
            enrolled_count=eff_enrolled,
            created_at=now,
            updated_at=now,
        )
        self.db.add(jadwal)
        self._sync_matakuliah_time(mk, hari_num, mulai, selesai)
        self.db.commit()
        self.db.refresh(jadwal)
        jadwal = self.get_schedule(jadwal.id)

        payload = {
            "kode_mk": jadwal.kode_mk,
            "nama_mk": mk.nama,
            "hari": HARI_MAP[hari_num],
            "jam": f"{mulai.strftime('%H:%M')}-{selesai.strftime('%H:%M')}",
            "ruangan": room.kode_ruangan,
            "dosen": jadwal.dosen,
            "affected_nims": sorted(nims),
            "conflicts": relevant_conflicts,
        }
        event_type = "CONFLICT_DETECTED" if relevant_conflicts else "SCHEDULE_CREATED"
        notifs = self.notification_manager.notify(event_type, payload)

        return {
            "schedule": self.schedule_to_response_dict(jadwal),
            "invalidated_krs_nims": [],
            "notifications_sent": [n.to_dict() for n in notifs],
            "conflicts": relevant_conflicts,
        }

    def update_schedule(
        self,
        schedule_id: int,
        *,
        ruangan_kode: str | None = None,
        dosen: str | None = None,
        hari: int | str | None = None,
        jam_mulai: time | str | None = None,
        jam_selesai: time | str | None = None,
        enrolled_count: int | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        """Memperbarui jadwal, memindahkan KRS terdampak ke REVISION (ACID), & notify Observer."""
        try:
            jadwal = self.get_schedule(schedule_id)
            old_snapshot = self.schedule_to_response_dict(jadwal)

            new_room = (
                self.get_room(ruangan_kode)
                if ruangan_kode is not None
                else jadwal.ruangan
            )
            new_hari = normalize_hari(hari) if hari is not None else jadwal.hari
            new_mulai = _coerce_time(jam_mulai) if jam_mulai is not None else jadwal.jam_mulai
            new_selesai = (
                _coerce_time(jam_selesai) if jam_selesai is not None else jadwal.jam_selesai
            )
            if new_mulai >= new_selesai:
                raise ScheduleError("jam_mulai harus lebih awal daripada jam_selesai")

            new_dosen = dosen.strip() if dosen is not None else jadwal.dosen
            base_enrolled = (
                enrolled_count if enrolled_count is not None else jadwal.enrolled_count
            )
            if base_enrolled < 0:
                raise ScheduleError("enrolled_count tidak boleh negatif")

            eff_enrolled, nims = self._effective_enrolled(
                jadwal.kode_mk, jadwal.semester, base_enrolled
            )
            check_room_capacity(eff_enrolled, new_room.kapasitas, new_room.kode_ruangan)

            others = [
                j
                for j in self.list_schedules(semester=jadwal.semester)
                if j.id != jadwal.id
            ]
            other_records = self._to_records(others, jadwal.semester)
            updated_record = ScheduleRecord(
                id=jadwal.id,
                kode_mk=jadwal.kode_mk,
                nama_mk=jadwal.matakuliah.nama if jadwal.matakuliah else jadwal.kode_mk,
                hari=new_hari,
                jam_mulai=new_mulai,
                jam_selesai=new_selesai,
                ruangan=new_room.kode_ruangan,
                dosen=new_dosen,
                enrolled_count=eff_enrolled,
                kapasitas=new_room.kapasitas,
                enrolled_nims=nims,
            )
            conflicts = detect_schedule_conflict([*other_records, updated_record])
            relevant_conflicts = [
                c
                for c in conflicts
                if any(s.get("id") == jadwal.id for s in c["affected_schedules"])
            ]
            if relevant_conflicts and not force:
                raise ScheduleConflictError(
                    relevant_conflicts[0]["detail"],
                    conflicts=relevant_conflicts,
                )

            jadwal.ruangan_kode = new_room.kode_ruangan
            jadwal.dosen = new_dosen
            jadwal.hari = new_hari
            jadwal.jam_mulai = new_mulai
            jadwal.jam_selesai = new_selesai
            jadwal.enrolled_count = eff_enrolled
            jadwal.updated_at = datetime.now(timezone.utc)

            if jadwal.matakuliah is not None:
                self._sync_matakuliah_time(
                    jadwal.matakuliah, new_hari, new_mulai, new_selesai
                )

            reason = (
                f"Jadwal {jadwal.kode_mk} berubah dari {old_snapshot['hari_nama']} "
                f"{old_snapshot['jam']} ({old_snapshot['ruangan_kode']}) ke "
                f"{HARI_MAP[new_hari]} {new_mulai.strftime('%H:%M')}-{new_selesai.strftime('%H:%M')} "
                f"({new_room.kode_ruangan}). Harap periksa dan ajukan ulang KRS Anda."
            )
            invalidated_ids, invalidated_nims, all_nims = self._invalidate_affected_krs(
                jadwal.kode_mk,
                jadwal.semester,
                reason=reason,
                aksi="invalidate_schedule_change",
            )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

        jadwal = self.get_schedule(schedule_id)
        new_snapshot = self.schedule_to_response_dict(jadwal)
        notify_nims = sorted(set(all_nims) | nims)

        notifs = self.notification_manager.notify(
            "SCHEDULE_CHANGED",
            {
                "old_schedule": old_snapshot,
                "new_schedule": {
                    **new_snapshot,
                    "ruangan": new_snapshot["ruangan_kode"],
                },
                "kode_mk": jadwal.kode_mk,
                "nama_mk": new_snapshot["nama_mk"],
                "dosen": new_dosen,
                "old_dosen": old_snapshot["dosen"],
                "affected_nims": notify_nims,
                "invalidated_krs_ids": invalidated_ids,
                "conflicts": relevant_conflicts,
            },
        )
        return {
            "schedule": new_snapshot,
            "invalidated_krs_nims": invalidated_nims,
            "notifications_sent": [n.to_dict() for n in notifs],
            "conflicts": relevant_conflicts,
        }

    def delete_schedule(self, schedule_id: int) -> dict[str, Any]:
        """Menghapus jadwal, memindahkan KRS terdampak ke REVISION (ACID), & notify Observer."""
        try:
            jadwal = self.get_schedule(schedule_id)
            old_snapshot = self.schedule_to_response_dict(jadwal)
            _, nims = self._effective_enrolled(
                jadwal.kode_mk, jadwal.semester, jadwal.enrolled_count
            )
            reason = (
                f"Jadwal {jadwal.kode_mk} ({old_snapshot['hari_nama']} {old_snapshot['jam']} "
                f"di {old_snapshot['ruangan_kode']}) telah dihapus. Harap sesuaikan kembali KRS Anda."
            )
            invalidated_ids, invalidated_nims, all_nims = self._invalidate_affected_krs(
                jadwal.kode_mk,
                jadwal.semester,
                reason=reason,
                aksi="invalidate_schedule_deleted",
            )
            self.db.delete(jadwal)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

        notify_nims = sorted(set(all_nims) | nims)
        notifs = self.notification_manager.notify(
            "SCHEDULE_DELETED",
            {
                **old_snapshot,
                "ruangan": old_snapshot["ruangan_kode"],
                "affected_nims": notify_nims,
                "invalidated_krs_ids": invalidated_ids,
            },
        )
        return {
            "detail": f"Jadwal {schedule_id} ({old_snapshot['kode_mk']}) berhasil dihapus",
            "deleted_schedule_id": schedule_id,
            "invalidated_krs_nims": invalidated_nims,
            "notifications_sent": [n.to_dict() for n in notifs],
        }

    # ------------------------------------------------------------------
    # Conflict Detection & AI-Powered Rescheduler
    # ------------------------------------------------------------------

    def get_all_conflicts(
        self, semester: str = "20251", include_general_overlap: bool = False
    ) -> list[dict[str, Any]]:
        schedules = self.list_schedules(semester=semester)
        records = self._to_records(schedules, semester)
        return detect_schedule_conflict(
            records, include_general_overlap=include_general_overlap
        )

    def suggest_alternatives(
        self,
        schedule_id: int,
        *,
        top_k: int = 3,
        use_ai: bool = True,
    ) -> dict[str, Any]:
        jadwal = self.get_schedule(schedule_id)
        all_schedules = self.list_schedules(semester=jadwal.semester)
        records = self._to_records(all_schedules, jadwal.semester)
        target_rec = next((r for r in records if r.id == schedule_id), None)
        if target_rec is None:
            raise ScheduleNotFoundError(f"Jadwal {schedule_id} tidak ditemukan")

        # Hitung slot sibuk milik mahasiswa yang mengambil MK ini agar disrupsi minimal
        student_busy_slots: list[dict[str, Any]] = []
        if target_rec.enrolled_nims:
            stmt_busy = (
                select(MataKuliah)
                .join(KRSDetail, KRSDetail.kode_mk == MataKuliah.kode_mk)
                .join(KRS, KRSDetail.krs_id == KRS.id)
                .where(
                    KRS.semester == jadwal.semester,
                    KRS.nim.in_(target_rec.enrolled_nims),
                    KRSDetail.kode_mk != jadwal.kode_mk,
                )
            )
            for mk in self.db.scalars(stmt_busy).all():
                student_busy_slots.append(
                    {
                        "hari": mk.hari,
                        "jam_mulai": mk.jam_mulai,
                        "jam_selesai": mk.jam_selesai,
                    }
                )

        rooms = self.list_rooms()
        result = suggest_alternative_schedules(
            conflicted_schedule=target_rec,
            existing_schedules=records,
            available_rooms=rooms,
            student_busy_slots=student_busy_slots,
            top_k=top_k,
            use_ai=use_ai,
        )
        return {
            "schedule": record_to_dict(target_rec),
            **result,
        }

    # ------------------------------------------------------------------
    # Demo Seeder untuk Dashboard Conflict Resolver UI
    # ------------------------------------------------------------------

    def seed_demo_data(self, semester: str = "20251") -> dict[str, Any]:
        """Mengisi data demo ruangan, mata kuliah, KRS, & skenario bentrok secara idempoten."""
        prodi = self.db.scalars(
            select(ProgramStudi).where(ProgramStudi.kode == "001")
        ).first()
        if prodi is None:
            prodi = ProgramStudi(
                kode="001", nama="Teknik Informatika", fakultas="Fakultas Teknik"
            )
            self.db.add(prodi)
            self.db.flush()

        jalur = self.db.scalars(
            select(JalurMasuk).where(JalurMasuk.nama == "SNBP")
        ).first()
        if jalur is None:
            jalur = JalurMasuk(nama="SNBP")
            self.db.add(jalur)
            self.db.flush()

        demo_students = [
            ("2025001-0001", "Rina Wulandari", "rina.demo@sevima.ac.id", "081234567891"),
            ("2025001-0002", "Dimas Pratama", "dimas.demo@sevima.ac.id", "081234567892"),
        ]
        for nim, nama, email, phone in demo_students:
            exists_mhs = self.db.scalars(
                select(CalonMahasiswa).where(CalonMahasiswa.nim == nim)
            ).first()
            if exists_mhs is None:
                self.db.add(
                    CalonMahasiswa(
                        nama_lengkap=nama,
                        email=email,
                        phone=phone,
                        tanggal_lahir=date(2005, 5, 10),
                        program_studi_id=prodi.id,
                        jalur_masuk_id=jalur.id,
                        status="approved",
                        nim=nim,
                    )
                )
        self.db.flush()

        demo_rooms = [
            ("A101", "Ruang Kuliah A101", 40, "Gedung A"),
            ("A102", "Ruang Kuliah A102", 45, "Gedung A"),
            ("A201", "Ruang Kuliah A201", 50, "Gedung A"),
            ("Lab-1", "Laboratorium Komputer 1", 35, "Gedung B"),
        ]
        for kode, nama, kap, gedung in demo_rooms:
            if self.db.get(Ruangan, kode) is None:
                self.db.add(
                    Ruangan(kode_ruangan=kode, nama=nama, kapasitas=kap, gedung=gedung)
                )

        demo_courses = [
            ("MA101", "Kalkulus I", 3, 1, time(8, 0), time(10, 0)),
            ("IF201", "Basis Data", 3, 1, time(8, 30), time(10, 30)),
            ("IF202", "Pemrograman Berorientasi Objek", 3, 1, time(9, 0), time(11, 0)),
            ("IF203", "Jaringan Komputer", 3, 2, time(13, 0), time(15, 0)),
        ]
        for kode, nama, sks, hari, mulai, selesai in demo_courses:
            if self.db.get(MataKuliah, kode) is None:
                self.db.add(
                    MataKuliah(
                        kode_mk=kode,
                        nama=nama,
                        sks=sks,
                        hari=hari,
                        jam_mulai=mulai,
                        jam_selesai=selesai,
                    )
                )
        self.db.flush()

        # Pastikan kedua mahasiswa demo memiliki KRS yang mengambil MA101
        krs_specs = [
            ("2025001-0001", KRSStatus.APPROVED, ["MA101", "IF203"]),
            ("2025001-0002", KRSStatus.SUBMITTED, ["MA101"]),
        ]
        for nim, target_status, course_codes in krs_specs:
            krs = self.db.scalars(
                select(KRS)
                .where(KRS.nim == nim, KRS.semester == semester)
                .options(selectinload(KRS.details))
            ).first()
            if krs is None:
                krs = KRS(
                    nim=nim,
                    semester=semester,
                    status=KRSStatus.DRAFT,
                    dosen_pa_id=10,
                )
                self.db.add(krs)
                self.db.flush()
                for c_code in course_codes:
                    krs.details.append(KRSDetail(kode_mk=c_code))
                if target_status == KRSStatus.SUBMITTED:
                    krs.transition(KRSStatus.SUBMITTED, actor="mahasiswa")
                elif target_status == KRSStatus.APPROVED:
                    krs.transition(KRSStatus.SUBMITTED, actor="mahasiswa")
                    krs.transition(KRSStatus.APPROVED, actor="dosen_pa", dosen_id=10)
        self.db.flush()

        existing_schedules = self.list_schedules(semester=semester)
        if not existing_schedules:
            now = datetime.now(timezone.utc)
            demo_schedules = [
                # Sesuai skenario Step 3 PDF: Kalkulus I (Senin 08:00, Ruang A101, 40 mhs)
                JadwalKuliah(
                    kode_mk="MA101",
                    ruangan_kode="A101",
                    dosen="Dr. Budi Santoso",
                    semester=semester,
                    hari=1,
                    jam_mulai=time(8, 0),
                    jam_selesai=time(10, 0),
                    enrolled_count=40,
                    created_at=now,
                    updated_at=now,
                ),
                # Bentrok ruangan dengan MA101 di A101
                JadwalKuliah(
                    kode_mk="IF201",
                    ruangan_kode="A101",
                    dosen="Dr. Siti Aminah",
                    semester=semester,
                    hari=1,
                    jam_mulai=time(8, 30),
                    jam_selesai=time(10, 30),
                    enrolled_count=32,
                    created_at=now,
                    updated_at=now,
                ),
                # Bentrok dosen dengan MA101 (sama-sama Dr. Budi Santoso di Senin pagi)
                JadwalKuliah(
                    kode_mk="IF202",
                    ruangan_kode="Lab-1",
                    dosen="Dr. Budi Santoso",
                    semester=semester,
                    hari=1,
                    jam_mulai=time(9, 0),
                    jam_selesai=time(11, 0),
                    enrolled_count=30,
                    created_at=now,
                    updated_at=now,
                ),
                # Jadwal sehat tanpa bentrok
                JadwalKuliah(
                    kode_mk="IF203",
                    ruangan_kode="A201",
                    dosen="Prof. Andi Wijaya",
                    semester=semester,
                    hari=2,
                    jam_mulai=time(13, 0),
                    jam_selesai=time(15, 0),
                    enrolled_count=28,
                    created_at=now,
                    updated_at=now,
                ),
            ]
            self.db.add_all(demo_schedules)

        self.db.commit()
        conflicts = self.get_all_conflicts(semester=semester)
        return {
            "detail": "Data demo jadwal & skenario bentrok siap digunakan",
            "total_schedules": len(self.list_schedules(semester=semester)),
            "total_conflicts": len(conflicts),
        }
