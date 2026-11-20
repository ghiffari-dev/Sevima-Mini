from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timezone
import logging
from typing import Any

from sqlalchemy import func, inspect, or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.security import get_password_hash
from app.models.calon_mahasiswa import CalonMahasiswa
from app.models.jalur_masuk import JalurMasuk
from app.models.krs import (
    Actor,
    KRS,
    KRSDetail,
    KRSLog,
    KRSStatus,
    MataKuliah,
    Notifikasi,
)
from app.models.program_studi import ProgramStudi
from app.models.schedule import (
    Dosen,
    HARI_MAP,
    Jadwal,
    Kelas,
    Outbox,
    Ruangan,
    ScheduleConflictError,
    ScheduleError,
    ScheduleNotFoundError,
    normalize_hari,
)
from app.models.user import Admin, User
from app.services.conflict_detector import (
    Conflict,
    cek_kapasitas,
    detect_conflicts_sweep,
    parse_time_value,
    pasangan,
)
from app.services.schedule_observer import (
    EventType,
    NotificationManager,
    OutboxDispatcher,
    ScheduleEvent,
    default_notification_manager,
)
from app.services.schedule_recommender import suggest_alternative_schedules

logger = logging.getLogger(__name__)


class SchedulingService:
    """Layanan terpadu penjadwalan (4 domain model), deteksi bentrok, locking pesimis, Observer, & invalidasi KRS."""

    def __init__(
        self,
        db: Session,
        notification_manager: NotificationManager | None = None,
    ) -> None:
        self.db = db
        self.notification_manager = notification_manager or default_notification_manager

    # ------------------------------------------------------------------
    # Master Data: Ruangan, Dosen, Kelas
    # ------------------------------------------------------------------

    def list_rooms(self) -> list[Ruangan]:
        stmt = select(Ruangan).order_by(Ruangan.kode.asc())
        return list(self.db.scalars(stmt).all())

    def get_room(self, kode_ruangan: str) -> Ruangan:
        room = self.db.get(Ruangan, kode_ruangan)
        if room is None:
            raise ScheduleNotFoundError(f"Ruangan {kode_ruangan} tidak ditemukan")
        return room

    def create_room(
        self,
        kode: str,
        nama: str = "",
        kapasitas: int = 40,
        gedung: str | None = None,
    ) -> Ruangan:
        kode_clean = kode.strip()
        if not kode_clean:
            raise ScheduleError("Kode ruangan wajib diisi")
        if kapasitas <= 0:
            raise ScheduleError("Kapasitas ruangan harus lebih besar dari 0")
        if self.db.get(Ruangan, kode_clean) is not None:
            raise ScheduleError(
                f"Ruangan {kode_clean} sudah terdaftar", status_code=409
            )
        room = Ruangan(
            kode=kode_clean,
            nama=nama.strip() or kode_clean,
            kapasitas=kapasitas,
            gedung=gedung.strip() if gedung else None,
        )
        self.db.add(room)
        self.db.commit()
        self.db.refresh(room)
        return room

    def list_lecturers(self) -> list[Dosen]:
        stmt = select(Dosen).order_by(Dosen.id.asc())
        return list(self.db.scalars(stmt).all())

    def get_lecturer(self, dosen_id: int) -> Dosen:
        dosen = self.db.get(Dosen, dosen_id)
        if dosen is None:
            raise ScheduleNotFoundError(f"Dosen dengan ID {dosen_id} tidak ditemukan")
        return dosen

    def create_lecturer(self, nidn: str, nama: str) -> Dosen:
        nidn_clean = nidn.strip()
        nama_clean = nama.strip()
        if not nidn_clean or not nama_clean:
            raise ScheduleError("NIDN dan nama dosen wajib diisi")
        exists = self.db.scalars(select(Dosen).where(Dosen.nidn == nidn_clean)).first()
        if exists is not None:
            raise ScheduleError(
                f"Dosen dengan NIDN {nidn_clean} sudah terdaftar", status_code=409
            )
        dosen = Dosen(nidn=nidn_clean, nama=nama_clean)
        self.db.add(dosen)
        self.db.commit()
        self.db.refresh(dosen)
        return dosen

    def list_classes(self, semester: str | None = None) -> list[Kelas]:
        stmt = select(Kelas).options(
            selectinload(Kelas.matakuliah),
            selectinload(Kelas.jadwals),
        )
        if semester is not None:
            stmt = stmt.where(Kelas.semester == semester)
        stmt = stmt.order_by(Kelas.kode_mk.asc(), Kelas.nama_kelas.asc(), Kelas.id.asc())
        return list(self.db.scalars(stmt).all())

    def get_class(self, kelas_id: int) -> Kelas:
        stmt = (
            select(Kelas)
            .where(Kelas.id == kelas_id)
            .options(
                selectinload(Kelas.matakuliah),
                selectinload(Kelas.jadwals),
            )
        )
        kelas = self.db.scalars(stmt).first()
        if kelas is None:
            raise ScheduleNotFoundError(f"Kelas dengan ID {kelas_id} tidak ditemukan")
        return kelas

    def create_class(
        self,
        kode_mk: str,
        nama_kelas: str,
        kuota: int = 40,
        semester: str = "20251",
    ) -> Kelas:
        mk = self.db.get(MataKuliah, kode_mk.strip())
        if mk is None:
            raise ScheduleNotFoundError(f"Mata kuliah {kode_mk} tidak ditemukan")
        if kuota <= 0:
            raise ScheduleError("Kuota kelas harus lebih besar dari 0")
        nama_clean = nama_kelas.strip()
        sem_clean = semester.strip()
        exists = self.db.scalars(
            select(Kelas).where(
                Kelas.kode_mk == mk.kode_mk,
                Kelas.nama_kelas == nama_clean,
                Kelas.semester == sem_clean,
            )
        ).first()
        if exists is not None:
            raise ScheduleError(
                f"Kelas {mk.kode_mk} ({nama_clean}) semester {sem_clean} sudah terdaftar",
                status_code=409,
            )
        kelas = Kelas(
            kode_mk=mk.kode_mk,
            nama_kelas=nama_clean,
            kuota=kuota,
            semester=sem_clean,
        )
        self.db.add(kelas)
        self.db.commit()
        return self.get_class(kelas.id)

    # ------------------------------------------------------------------
    # Helper Internal: Locking, Query Bentrok SQL, & Penghitungan Peserta
    # ------------------------------------------------------------------

    def _kunci(self, ruangan_kode: str, dosen_id: int) -> tuple[Ruangan, Dosen]:
        """Mengunci baris Ruangan lalu Dosen (urutan tetap anti-deadlock) memakai FOR UPDATE."""
        ruangan = self.db.scalars(
            select(Ruangan).where(Ruangan.kode == ruangan_kode).with_for_update()
        ).first()
        if ruangan is None:
            raise ScheduleNotFoundError(f"Ruangan {ruangan_kode} tidak ditemukan")

        dosen = self.db.scalars(
            select(Dosen).where(Dosen.id == dosen_id).with_for_update()
        ).first()
        if dosen is None:
            raise ScheduleNotFoundError(f"Dosen dengan ID {dosen_id} tidak ditemukan")

        return ruangan, dosen

    def _cari_bentrok_sql(
        self,
        *,
        hari: int,
        jam_mulai: time,
        jam_selesai: time,
        ruangan_kode: str,
        dosen_id: int,
        semester: str | None = None,
        exclude_id: int | None = None,
    ) -> list[Conflict]:
        """Mencari bentrok ruangan & dosen langsung di SQL memanfaatkan composite index."""
        filters = [
            Jadwal.hari == hari,
            Jadwal.jam_mulai < jam_selesai,
            Jadwal.jam_selesai > jam_mulai,
        ]
        if exclude_id is not None:
            filters.append(Jadwal.id != exclude_id)

        def _query_ids(dim_filter: Any) -> list[int]:
            stmt = select(Jadwal.id).join(Jadwal.kelas).where(*filters, dim_filter)
            if semester is not None:
                stmt = stmt.where(Kelas.semester == semester)
            stmt = stmt.order_by(Jadwal.id.asc())
            return [int(jid) for jid in self.db.scalars(stmt).all()]

        conflicts: list[Conflict] = []
        for other_id in _query_ids(Jadwal.ruangan_kode == ruangan_kode):
            affected = pasangan(exclude_id, other_id) if exclude_id is not None else (other_id,)
            conflicts.append(Conflict("room_conflict", affected))
        for other_id in _query_ids(Jadwal.dosen_id == dosen_id):
            affected = pasangan(exclude_id, other_id) if exclude_id is not None else (other_id,)
            conflicts.append(Conflict("lecturer_conflict", affected))
        return conflicts

    def _nims_for_class(self, kelas: Kelas) -> set[str]:
        stmt = (
            select(KRS.nim)
            .join(KRSDetail, KRSDetail.krs_id == KRS.id)
            .where(
                KRS.semester == kelas.semester,
                or_(
                    KRSDetail.kelas_id == kelas.id,
                    (KRSDetail.kelas_id.is_(None)) & (KRSDetail.kode_mk == kelas.kode_mk),
                ),
            )
        )
        return set(self.db.scalars(stmt).all())

    def _nims_by_class_ids(self, schedules: list[Jadwal]) -> dict[int, set[str]]:
        if not schedules:
            return {}
        semesters = {j.kelas.semester for j in schedules if j.kelas}
        kode_mks = {j.kelas.kode_mk for j in schedules if j.kelas}
        if not semesters or not kode_mks:
            return {}

        stmt = (
            select(KRSDetail.kelas_id, KRSDetail.kode_mk, KRS.semester, KRS.nim)
            .join(KRS, KRSDetail.krs_id == KRS.id)
            .where(KRS.semester.in_(semesters), KRSDetail.kode_mk.in_(kode_mks))
        )
        by_kelas: dict[int, set[str]] = defaultdict(set)
        by_mk_sem: dict[tuple[str, str], set[str]] = defaultdict(set)
        for k_id, k_mk, sem, nim in self.db.execute(stmt).all():
            if k_id is not None:
                by_kelas[int(k_id)].add(nim)
            else:
                by_mk_sem[(k_mk, sem)].add(nim)

        result: dict[int, set[str]] = {}
        for j in schedules:
            k = j.kelas
            if k is None:
                continue
            nims = set(by_kelas.get(k.id, set())) | set(by_mk_sem.get((k.kode_mk, k.semester), set()))
            result[j.id] = nims
        return result

    def _invalidate_affected_krs(
        self,
        *,
        kelas: Kelas,
        reason: str,
        aksi: str,
    ) -> tuple[list[int], list[str], list[str]]:
        """Mengembalikan KRS SUBMITTED/APPROVED terdampak ke REVISION via Actor.SYSTEM dalam transaksi ACID."""
        stmt = (
            select(KRS)
            .join(KRSDetail, KRSDetail.krs_id == KRS.id)
            .where(
                KRS.semester == kelas.semester,
                or_(
                    KRSDetail.kelas_id == kelas.id,
                    (KRSDetail.kelas_id.is_(None)) & (KRSDetail.kode_mk == kelas.kode_mk),
                ),
            )
            .distinct()
            .with_for_update()
        )
        affected_krs = list(self.db.scalars(stmt).all())
        invalidated_ids: list[int] = []
        invalidated_nims: list[str] = []
        all_nims: list[str] = []

        for krs in affected_krs:
            all_nims.append(krs.nim)
            if krs.status in (KRSStatus.SUBMITTED, KRSStatus.APPROVED):
                krs.transition(
                    KRSStatus.REVISION,
                    actor=Actor.SYSTEM,
                    catatan=reason,
                )
                self.db.add(KRSLog(krs_id=krs.id, aksi=aksi, oleh=None))
                self.db.add(Notifikasi(nim=krs.nim, pesan=reason))
                invalidated_ids.append(krs.id)
                invalidated_nims.append(krs.nim)

        return invalidated_ids, invalidated_nims, all_nims

    # ------------------------------------------------------------------
    # CRUD Jadwal Kuliah (create & update berbagi _simpan)
    # ------------------------------------------------------------------

    def list_schedules(self, semester: str | None = None) -> list[Jadwal]:
        stmt = (
            select(Jadwal)
            .join(Jadwal.kelas)
            .options(
                selectinload(Jadwal.kelas).selectinload(Kelas.matakuliah),
                selectinload(Jadwal.ruangan),
                selectinload(Jadwal.dosen),
            )
        )
        if semester is not None:
            stmt = stmt.where(Kelas.semester == semester)
        stmt = stmt.order_by(Jadwal.hari.asc(), Jadwal.jam_mulai.asc(), Jadwal.id.asc())
        return list(self.db.scalars(stmt).all())

    def get_schedule(self, schedule_id: int) -> Jadwal:
        stmt = (
            select(Jadwal)
            .where(Jadwal.id == schedule_id)
            .options(
                selectinload(Jadwal.kelas).selectinload(Kelas.matakuliah),
                selectinload(Jadwal.ruangan),
                selectinload(Jadwal.dosen),
            )
        )
        jadwal = self.db.scalars(stmt).first()
        if jadwal is None:
            raise ScheduleNotFoundError(f"Jadwal dengan ID {schedule_id} tidak ditemukan")
        return jadwal

    def schedule_to_response_dict(
        self,
        jadwal: Jadwal,
        nims_override: set[str] | None = None,
    ) -> dict[str, Any]:
        kelas = jadwal.kelas
        mk = kelas.matakuliah if kelas else None
        ruangan = jadwal.ruangan
        dosen = jadwal.dosen

        nims = (
            nims_override
            if nims_override is not None
            else (self._nims_for_class(kelas) if kelas else set())
        )
        terdaftar = len(nims)
        kuota = kelas.kuota if kelas else 0
        eff_enrolled = max(kuota, terdaftar)

        return {
            "id": jadwal.id,
            "kelas_id": jadwal.kelas_id,
            "kode_mk": kelas.kode_mk if kelas else "",
            "nama_mk": mk.nama if mk else (kelas.kode_mk if kelas else ""),
            "nama_kelas": kelas.nama_kelas if kelas else "",
            "kuota": kuota,
            "terdaftar": terdaftar,
            "ruangan_kode": jadwal.ruangan_kode,
            "ruangan_nama": ruangan.nama if ruangan else jadwal.ruangan_kode,
            "kapasitas": ruangan.kapasitas if ruangan else 0,
            "dosen_id": jadwal.dosen_id,
            "dosen_nidn": dosen.nidn if dosen else "",
            "dosen": dosen.nama if dosen else "",
            "semester": kelas.semester if kelas else "20251",
            "hari": jadwal.hari,
            "hari_nama": HARI_MAP[jadwal.hari],
            "jam_mulai": jadwal.jam_mulai.strftime("%H:%M"),
            "jam_selesai": jadwal.jam_selesai.strftime("%H:%M"),
            "jam": f"{jadwal.jam_mulai.strftime('%H:%M')}-{jadwal.jam_selesai.strftime('%H:%M')}",
            "enrolled_count": eff_enrolled,
            "sequence": int(getattr(jadwal, "sequence", 0) or 0),
        }

    def _build_snapshot_from_parts(
        self,
        *,
        schedule_id: int,
        kelas: Kelas,
        ruangan: Ruangan,
        dosen: Dosen,
        hari: int,
        mulai: time,
        selesai: time,
        sequence: int,
        nims: set[str],
    ) -> dict[str, Any]:
        mk = kelas.matakuliah
        terdaftar = len(nims)
        kuota = kelas.kuota
        return {
            "id": schedule_id,
            "kelas_id": kelas.id,
            "kode_mk": kelas.kode_mk,
            "nama_mk": mk.nama if mk else kelas.kode_mk,
            "nama_kelas": kelas.nama_kelas,
            "kuota": kuota,
            "terdaftar": terdaftar,
            "ruangan_kode": ruangan.kode,
            "ruangan_nama": ruangan.nama,
            "kapasitas": ruangan.kapasitas,
            "dosen_id": dosen.id,
            "dosen_nidn": dosen.nidn,
            "dosen": dosen.nama,
            "semester": kelas.semester,
            "hari": hari,
            "hari_nama": HARI_MAP[hari],
            "jam_mulai": mulai.strftime("%H:%M"),
            "jam_selesai": selesai.strftime("%H:%M"),
            "jam": f"{mulai.strftime('%H:%M')}-{selesai.strftime('%H:%M')}",
            "enrolled_count": max(kuota, terdaftar),
            "sequence": sequence,
        }

    def _run_dispatcher_safe(self) -> list[dict[str, Any]]:
        """Menjalankan OutboxDispatcher setelah komit; kegagalan pengiriman tidak membatalkan perubahan jadwal."""
        try:
            summary = OutboxDispatcher(self.db, self.notification_manager).run()
            return [r.to_dict() for r in summary.records]
        except Exception as exc:
            logger.warning("OutboxDispatcher gagal setelah komit: %s", exc)
            return []

    def _simpan(
        self,
        jadwal: Jadwal,
        *,
        kelas_id: int,
        ruangan_kode: str,
        dosen_id: int,
        hari: int | str,
        jam_mulai: time | str,
        jam_selesai: time | str,
        force: bool,
        is_new: bool,
        old_snapshot: dict[str, Any] | None = None,
        dispatch_now: bool = True,
    ) -> dict[str, Any]:
        """Alur atomik bersama create & update: validasi -> kunci -> cek bentrok SQL -> cek kapasitas -> invalidasi KRS + outbox -> commit -> dispatch."""
        outbox_event_id: str | None = None
        invalidated_nims: list[str] = []
        serialized_conflicts: list[dict[str, Any]] = []

        try:
            kelas = self.get_class(kelas_id)
            hari_num = normalize_hari(hari)
            mulai = parse_time_value(jam_mulai)
            selesai = parse_time_value(jam_selesai)
            if mulai >= selesai:
                raise ScheduleError("jam_mulai harus lebih awal daripada jam_selesai")

            # 1. Kunci baris Ruangan dulu lalu Dosen (anti-deadlock)
            ruangan, dosen = self._kunci(ruangan_kode.strip(), dosen_id)

            # 2. Cari bentrok di SQL memakai composite index
            conflicts = self._cari_bentrok_sql(
                hari=hari_num,
                jam_mulai=mulai,
                jam_selesai=selesai,
                ruangan_kode=ruangan.kode,
                dosen_id=dosen.id,
                semester=kelas.semester,
                exclude_id=None if is_new else jadwal.id,
            )
            if conflicts and not force:
                ringkas = ", ".join(
                    f"{c.type} (jadwal {', '.join(str(x) for x in c.affected)})"
                    for c in conflicts
                )
                raise ScheduleConflictError(
                    f"Jadwal bentrok: {ringkas}",
                    conflicts=conflicts,
                )
            serialized_conflicts = [c.to_dict() for c in conflicts]

            # 3. Cek kapasitas ruangan: max(kuota, terdaftar) <= ruangan.kapasitas
            cek_kapasitas(self.db, ruangan, kelas)

            # 4. Salin nilai & tambahkan objek paling akhir agar autoflush tidak mengganggu query bentrok
            now = datetime.now(timezone.utc)
            jadwal.kelas_id = kelas.id
            jadwal.ruangan_kode = ruangan.kode
            jadwal.dosen_id = dosen.id
            jadwal.hari = hari_num
            jadwal.jam_mulai = mulai
            jadwal.jam_selesai = selesai
            jadwal.updated_at = now
            if is_new:
                jadwal.sequence = 0
                jadwal.created_at = now
                self.db.add(jadwal)
            else:
                jadwal.sequence = int(getattr(jadwal, "sequence", 0) or 0) + 1

            if not is_new and old_snapshot is not None:
                reason = (
                    f"Jadwal {kelas.kode_mk} ({kelas.nama_kelas}) berubah dari "
                    f"{old_snapshot['hari_nama']} {old_snapshot['jam']} ({old_snapshot['ruangan_kode']}) ke "
                    f"{HARI_MAP[hari_num]} {mulai.strftime('%H:%M')}-{selesai.strftime('%H:%M')} "
                    f"({ruangan.kode}). Harap periksa dan ajukan ulang KRS Anda."
                )
                invalidated_ids, invalidated_nims, all_nims = self._invalidate_affected_krs(
                    kelas=kelas,
                    reason=reason,
                    aksi="invalidate_schedule_change",
                )
                nims_class = self._nims_for_class(kelas)
                notify_nims = sorted(set(all_nims) | nims_class)
                after_snapshot = self._build_snapshot_from_parts(
                    schedule_id=jadwal.id,
                    kelas=kelas,
                    ruangan=ruangan,
                    dosen=dosen,
                    hari=hari_num,
                    mulai=mulai,
                    selesai=selesai,
                    sequence=jadwal.sequence,
                    nims=nims_class,
                )
                event = ScheduleEvent(
                    event_type=EventType.SCHEDULE_CHANGED,
                    before=old_snapshot,
                    after=after_snapshot,
                    meta={
                        "affected_nims": notify_nims,
                        "invalidated_krs_ids": invalidated_ids,
                        "conflicts": serialized_conflicts,
                        "dosen": after_snapshot["dosen"],
                        "old_dosen": old_snapshot.get("dosen", ""),
                    },
                )
                outbox_event_id = event.event_id
                self.db.add(Outbox.from_event(event))

            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

        saved = self.get_schedule(jadwal.id)
        nims = self._nims_for_class(saved.kelas)
        new_snapshot = self.schedule_to_response_dict(saved, nims_override=nims)

        notifications_sent: list[dict[str, Any]] = []
        if not is_new and dispatch_now:
            notifications_sent = self._run_dispatcher_safe()

        return {
            "schedule": new_snapshot,
            "invalidated_krs_nims": invalidated_nims,
            "notifications_sent": notifications_sent,
            "conflicts": serialized_conflicts,
            "outbox_event_id": outbox_event_id,
        }

    def create_schedule(
        self,
        *,
        kelas_id: int,
        ruangan_kode: str,
        dosen_id: int,
        hari: int | str,
        jam_mulai: time | str,
        jam_selesai: time | str,
        force: bool = False,
    ) -> dict[str, Any]:
        return self._simpan(
            Jadwal(),
            kelas_id=kelas_id,
            ruangan_kode=ruangan_kode,
            dosen_id=dosen_id,
            hari=hari,
            jam_mulai=jam_mulai,
            jam_selesai=jam_selesai,
            force=force,
            is_new=True,
        )

    def update_schedule(
        self,
        schedule_id: int,
        *,
        kelas_id: int | None = None,
        ruangan_kode: str | None = None,
        dosen_id: int | None = None,
        hari: int | str | None = None,
        jam_mulai: time | str | None = None,
        jam_selesai: time | str | None = None,
        force: bool = False,
        dispatch_now: bool = True,
    ) -> dict[str, Any]:
        """Memperbarui jadwal, memindahkan KRS terdampak ke REVISION (ACID), menulis Outbox, & dispatch setelah komit."""
        jadwal = self.get_schedule(schedule_id)
        old_snapshot = self.schedule_to_response_dict(jadwal)
        return self._simpan(
            jadwal,
            kelas_id=kelas_id if kelas_id is not None else jadwal.kelas_id,
            ruangan_kode=ruangan_kode if ruangan_kode is not None else jadwal.ruangan_kode,
            dosen_id=dosen_id if dosen_id is not None else jadwal.dosen_id,
            hari=hari if hari is not None else jadwal.hari,
            jam_mulai=jam_mulai if jam_mulai is not None else jadwal.jam_mulai,
            jam_selesai=jam_selesai if jam_selesai is not None else jadwal.jam_selesai,
            force=force,
            is_new=False,
            old_snapshot=old_snapshot,
            dispatch_now=dispatch_now,
        )

    def delete_schedule(
        self, schedule_id: int, *, dispatch_now: bool = True
    ) -> dict[str, Any]:
        """Menghapus jadwal, memindahkan KRS terdampak ke REVISION, menulis Outbox (ACID), & dispatch setelah komit."""
        outbox_event_id: str | None = None
        try:
            jadwal = self.get_schedule(schedule_id)
            kelas = jadwal.kelas
            nims = self._nims_for_class(kelas)
            old_snapshot = self.schedule_to_response_dict(jadwal, nims_override=nims)
            reason = (
                f"Jadwal {kelas.kode_mk} ({kelas.nama_kelas}) ({old_snapshot['hari_nama']} "
                f"{old_snapshot['jam']} di {old_snapshot['ruangan_kode']}) telah dihapus. "
                "Harap sesuaikan kembali KRS Anda."
            )
            invalidated_ids, invalidated_nims, all_nims = self._invalidate_affected_krs(
                kelas=kelas,
                reason=reason,
                aksi="invalidate_schedule_deleted",
            )
            notify_nims = sorted(set(all_nims) | nims)
            event = ScheduleEvent(
                event_type=EventType.SCHEDULE_DELETED,
                before=old_snapshot,
                after=None,
                meta={
                    "affected_nims": notify_nims,
                    "invalidated_krs_ids": invalidated_ids,
                    "dosen": old_snapshot.get("dosen", ""),
                },
            )
            outbox_event_id = event.event_id
            self.db.add(Outbox.from_event(event))
            self.db.delete(jadwal)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

        notifications_sent: list[dict[str, Any]] = []
        if dispatch_now:
            notifications_sent = self._run_dispatcher_safe()

        return {
            "detail": f"Jadwal {schedule_id} ({old_snapshot['kode_mk']} {old_snapshot['nama_kelas']}) berhasil dihapus",
            "deleted_schedule_id": schedule_id,
            "invalidated_krs_nims": invalidated_nims,
            "notifications_sent": notifications_sent,
            "outbox_event_id": outbox_event_id,
        }

    def list_outbox(self, limit: int = 50) -> list[Outbox]:
        """Mengambil daftar baris Transactional Outbox terbaru untuk monitoring admin."""
        stmt = select(Outbox).order_by(Outbox.id.desc()).limit(limit)
        return list(self.db.scalars(stmt).all())

    def dispatch_pending_outbox(self, limit: int = 50) -> dict[str, Any]:
        """Menjalankan OutboxDispatcher secara eksplisit untuk memproses baris pending."""
        summary = OutboxDispatcher(self.db, self.notification_manager).run(limit=limit)
        return {
            "picked": summary.picked,
            "sent": summary.sent,
            "retried": summary.retried,
            "failed": summary.failed,
            "failed_observers": summary.failed_observers,
            "notifications_sent": [r.to_dict() for r in summary.records],
        }

    # ------------------------------------------------------------------
    # Conflict Detection (Sort & Sweep) & AI-Powered Rescheduler
    # ------------------------------------------------------------------

    def get_all_conflicts(self, semester: str = "20251") -> list[dict[str, Any]]:
        jadwals = self.list_schedules(semester=semester)
        nims_map = self._nims_by_class_ids(jadwals)
        info_map = {
            j.id: self.schedule_to_response_dict(j, nims_override=nims_map.get(j.id, set()))
            for j in jadwals
        }
        conflicts = detect_conflicts_sweep(jadwals)

        enriched: list[dict[str, Any]] = []
        for c in conflicts:
            affected_dicts = [info_map[jid] for jid in c.affected if jid in info_map]
            if len(affected_dicts) >= 2:
                s1, s2 = affected_dicts[0], affected_dicts[1]
                if c.type == "room_conflict":
                    detail = (
                        f"Bentrok ruangan {s1['ruangan_kode']} pada {s1['hari_nama']} "
                        f"({s1['jam']} vs {s2['jam']})"
                    )
                else:
                    detail = (
                        f"Bentrok dosen {s1['dosen']} pada {s1['hari_nama']} "
                        f"({s1['jam']} vs {s2['jam']})"
                    )
            else:
                detail = f"{c.type}: jadwal {list(c.affected)}"
            enriched.append(
                {
                    "type": c.type,
                    "affected": list(c.affected),
                    "affected_schedules": affected_dicts,
                    "detail": detail,
                }
            )
        return enriched

    def suggest_alternatives(
        self,
        schedule_id: int,
        *,
        top_k: int = 3,
        use_ai: bool = True,
    ) -> dict[str, Any]:
        jadwal = self.get_schedule(schedule_id)
        semester = jadwal.kelas.semester
        all_jadwals = self.list_schedules(semester=semester)
        nims_map = self._nims_by_class_ids(all_jadwals)

        target_nims = nims_map.get(jadwal.id, set())
        target_dict = self.schedule_to_response_dict(jadwal, nims_override=target_nims)
        all_dicts = [
            self.schedule_to_response_dict(j, nims_override=nims_map.get(j.id, set()))
            for j in all_jadwals
        ]

        student_busy_slots: list[dict[str, Any]] = []
        if target_nims:
            stmt_busy = (
                select(Jadwal)
                .join(Kelas, Jadwal.kelas_id == Kelas.id)
                .join(
                    KRSDetail,
                    or_(
                        KRSDetail.kelas_id == Kelas.id,
                        (KRSDetail.kelas_id.is_(None)) & (KRSDetail.kode_mk == Kelas.kode_mk),
                    ),
                )
                .join(KRS, KRSDetail.krs_id == KRS.id)
                .where(
                    KRS.semester == semester,
                    KRS.nim.in_(target_nims),
                    Kelas.kode_mk != jadwal.kelas.kode_mk,
                )
                .distinct()
            )
            for busy in self.db.scalars(stmt_busy).all():
                student_busy_slots.append(
                    {
                        "hari": busy.hari,
                        "jam_mulai": busy.jam_mulai,
                        "jam_selesai": busy.jam_selesai,
                    }
                )

        rooms = self.list_rooms()
        result = suggest_alternative_schedules(
            conflicted_schedule=target_dict,
            existing_schedules=all_dicts,
            available_rooms=rooms,
            student_busy_slots=student_busy_slots,
            top_k=top_k,
            use_ai=use_ai,
        )
        return {
            "schedule": target_dict,
            **result,
        }

    # ------------------------------------------------------------------
    # Demo Seeder untuk Dashboard Conflict Resolver UI
    # ------------------------------------------------------------------

    def seed_demo_data(self, semester: str = "20251") -> dict[str, Any]:
        """Mengisi data demo 4 model (Ruangan, Dosen, Kelas paralel, Jadwal bentrok), Admin demo, & KRS secara idempoten."""
        bind = self.db.get_bind()
        if inspect(bind).has_table(User.__tablename__) and inspect(bind).has_table(
            Admin.__tablename__
        ):
            demo_admin = self.db.scalars(
                select(User).where(User.email == settings.ADMIN_DEMO_EMAIL)
            ).first()
            if demo_admin is None:
                self.db.add(
                    Admin(
                        id="ADM-001",
                        nama="Admin Akademik",
                        email=settings.ADMIN_DEMO_EMAIL,
                        hashed_password=get_password_hash(settings.ADMIN_DEMO_PASSWORD),
                        admin_role="admin_akademik",
                    )
                )
                self.db.flush()

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
                self.db.add(Ruangan(kode=kode, nama=nama, kapasitas=kap, gedung=gedung))

        demo_lecturers = [
            ("0010018001", "Dr. Budi Santoso"),
            ("0015028202", "Dr. Siti Aminah"),
            ("0020037503", "Prof. Andi Wijaya"),
        ]
        dosen_by_nidn: dict[str, Dosen] = {}
        for nidn, nama in demo_lecturers:
            d = self.db.scalars(select(Dosen).where(Dosen.nidn == nidn)).first()
            if d is None:
                d = Dosen(nidn=nidn, nama=nama)
                self.db.add(d)
                self.db.flush()
            dosen_by_nidn[nidn] = d

        demo_courses = [
            ("MA101", "Kalkulus I", 3),
            ("IF201", "Basis Data", 3),
            ("IF202", "Pemrograman Berorientasi Objek", 3),
            ("IF203", "Jaringan Komputer", 3),
        ]
        for kode, nama, sks in demo_courses:
            if self.db.get(MataKuliah, kode) is None:
                self.db.add(MataKuliah(kode_mk=kode, nama=nama, sks=sks))
        self.db.flush()

        demo_classes = [
            ("MA101", "A", 40),
            ("IF201", "A", 32),
            ("IF201", "B", 30),
            ("IF202", "A", 30),
            ("IF203", "A", 28),
        ]
        kelas_map: dict[tuple[str, str], Kelas] = {}
        for kode_mk, nama_kelas, kuota in demo_classes:
            kls = self.db.scalars(
                select(Kelas).where(
                    Kelas.kode_mk == kode_mk,
                    Kelas.nama_kelas == nama_kelas,
                    Kelas.semester == semester,
                )
            ).first()
            if kls is None:
                kls = Kelas(
                    kode_mk=kode_mk,
                    nama_kelas=nama_kelas,
                    kuota=kuota,
                    semester=semester,
                )
                self.db.add(kls)
                self.db.flush()
            kelas_map[(kode_mk, nama_kelas)] = kls

        krs_specs = [
            ("2025001-0001", KRSStatus.APPROVED, [("MA101", "A"), ("IF203", "A")]),
            ("2025001-0002", KRSStatus.SUBMITTED, [("MA101", "A")]),
        ]
        for nim, target_status, course_specs in krs_specs:
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
                for c_code, c_kelas in course_specs:
                    kls = kelas_map[(c_code, c_kelas)]
                    krs.details.append(KRSDetail(kode_mk=c_code, kelas_id=kls.id))
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
                # Kalkulus I Kelas A (Senin 08:00-10:00, Ruang A101, Dr. Budi Santoso)
                Jadwal(
                    kelas_id=kelas_map[("MA101", "A")].id,
                    ruangan_kode="A101",
                    dosen_id=dosen_by_nidn["0010018001"].id,
                    hari=1,
                    jam_mulai=time(8, 0),
                    jam_selesai=time(10, 0),
                    created_at=now,
                    updated_at=now,
                ),
                # Bentrok ruangan dengan MA101 A di A101
                Jadwal(
                    kelas_id=kelas_map[("IF201", "A")].id,
                    ruangan_kode="A101",
                    dosen_id=dosen_by_nidn["0015028202"].id,
                    hari=1,
                    jam_mulai=time(8, 30),
                    jam_selesai=time(10, 30),
                    created_at=now,
                    updated_at=now,
                ),
                # Bentrok dosen dengan MA101 A (sama-sama Dr. Budi Santoso di Senin pagi)
                Jadwal(
                    kelas_id=kelas_map[("IF202", "A")].id,
                    ruangan_kode="Lab-1",
                    dosen_id=dosen_by_nidn["0010018001"].id,
                    hari=1,
                    jam_mulai=time(9, 0),
                    jam_selesai=time(11, 0),
                    created_at=now,
                    updated_at=now,
                ),
                # Jadwal sehat tanpa bentrok
                Jadwal(
                    kelas_id=kelas_map[("IF203", "A")].id,
                    ruangan_kode="A201",
                    dosen_id=dosen_by_nidn["0020037503"].id,
                    hari=2,
                    jam_mulai=time(13, 0),
                    jam_selesai=time(15, 0),
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
