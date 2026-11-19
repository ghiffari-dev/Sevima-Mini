from __future__ import annotations

from datetime import datetime, timezone
import logging
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.orm.exc import StaleDataError

from app.models.krs import (
    Actor,
    ForbiddenError,
    KRS,
    KRSDetail,
    KRSError,
    KRSForbiddenError,
    KRSLockedError,
    KRSLog,
    KRSStatus,
    MataKuliah,
    Notifikasi,
    StateTransitionError,
    TRANSITIONS,
    TransitionError,
)
from app.services.krs_validator import (
    KRSContext,
    ValidationResult,
    Validator,
    build_chain,
    default_validators,
)

logger = logging.getLogger(__name__)
EDITABLE = {KRSStatus.DRAFT, KRSStatus.REVISION}


class KRSManager:
    """Satu pintu untuk semua perubahan KRS (Minggu 05 & Minggu 06)."""

    def __init__(
        self,
        db: Session,
        validators: list[Validator] | None = None,
        semester: str = "20251",
        dosen_pa_id: int | None = None,
    ) -> None:
        self.db, self.semester = db, semester
        self.dosen_pa_id = dosen_pa_id
        self.validators = validators if validators is not None else default_validators()
        self.chain = build_chain(self.validators)

    def _krs_terkunci(self, nim: str) -> KRS:
        """Mengambil KRS mahasiswa di semester aktif dengan FOR UPDATE (atau buat DRAFT jika belum ada)."""
        stmt = (
            select(KRS)
            .where(KRS.nim == nim, KRS.semester == self.semester)
            .options(
                selectinload(KRS.details)
                .selectinload(KRSDetail.matakuliah)
                .selectinload(MataKuliah.prasyarat)
            )
            .with_for_update()
        )
        krs = self.db.scalars(stmt).first()
        if krs is None:
            krs = KRS(
                nim=nim,
                semester=self.semester,
                status=KRSStatus.DRAFT,
                dosen_pa_id=self.dosen_pa_id,
            )
            self.db.add(krs)
            self.db.flush()
        return krs

    def _cek_kepemilikan_mahasiswa(self, krs: KRS, requester_nim: str | None) -> None:
        """Memastikan hanya mahasiswa pemilik KRS yang boleh mengubah/mengajukan KRS (403 Forbidden)."""
        if requester_nim is not None and requester_nim != krs.nim:
            raise KRSForbiddenError(
                f"Akses ditolak: KRS milik {krs.nim} tidak dapat diakses oleh {requester_nim}"
            )

    def _cek_kepemilikan_dosen_pa(self, krs: KRS, dosen_pa_id: int) -> None:
        """Memastikan hanya Dosen PA mahasiswa yang bersangkutan yang berhak approve/revise (403 Forbidden)."""
        if krs.dosen_pa_id is None or dosen_pa_id != krs.dosen_pa_id:
            raise ForbiddenError(
                "Anda bukan dosen PA mahasiswa ini (Approve/revise hanya oleh Dosen PA)"
            )

    def _cek_versi_krs(self, krs: KRS, expected_version: int | None) -> None:
        """Mendeteksi layar basi (optimistic lock): tolak 409 jika version yang dilihat dosen sudah berubah."""
        if expected_version is not None and krs.version != expected_version:
            raise TransitionError("KRS sudah berubah, muat ulang", status_code=409)

    def _validate_krs_obj(self, krs: KRS) -> list[ValidationResult]:
        """Menjalankan chain validator untuk semua aturan dan semua mata kuliah di kartu KRS, mengembalikan daftar yang gagal."""
        gagal: list[ValidationResult] = []
        accumulated_details: list[KRSDetail] = []
        for d in krs.details:
            ctx = KRSContext(
                krs.nim, krs.semester, list(accumulated_details), d.matakuliah, self.db
            )
            res = self.chain.validate(ctx)
            if not res.ok:
                gagal.append(res)
            else:
                accumulated_details.append(d)
        return gagal

    def add_course(
        self, nim: str, kode_mk: str, requester_nim: str | None = None
    ) -> KRSDetail:
        """Menambahkan 1 mata kuliah ke kartu KRS (hanya saat status DRAFT atau REVISION)."""
        krs = self._krs_terkunci(nim)
        self._cek_kepemilikan_mahasiswa(krs, requester_nim)
        if krs.status not in EDITABLE:
            raise KRSLockedError(f"KRS {krs.status.value} tidak bisa diubah")

        stmt_mk = (
            select(MataKuliah)
            .where(MataKuliah.kode_mk == kode_mk)
            .options(selectinload(MataKuliah.prasyarat))
        )
        mk = self.db.scalars(stmt_mk).first()
        if mk is None:
            raise KRSError(f"Mata kuliah {kode_mk} tidak ditemukan")

        ctx = KRSContext(krs.nim, krs.semester, list(krs.details), mk, self.db)
        hasil = self.chain.validate(ctx)
        if not hasil.ok:
            raise KRSError(hasil.message)

        detail = KRSDetail(kode_mk=mk.kode_mk, matakuliah=mk)
        krs.details.append(detail)
        # Sentuh diubah_pada agar baris krs di-update dan version naik (Slide 4)
        krs.diubah_pada = datetime.now(timezone.utc)
        self.db.commit()  # satu transaksi · kunci dilepas
        return detail

    def remove_course(
        self, nim: str, kode_mk: str, requester_nim: str | None = None
    ) -> None:
        """Menghapus 1 mata kuliah dari kartu KRS (hanya saat status DRAFT atau REVISION)."""
        krs = self._krs_terkunci(nim)
        self._cek_kepemilikan_mahasiswa(krs, requester_nim)
        if krs.status not in EDITABLE:
            raise KRSLockedError(f"KRS {krs.status.value} tidak bisa diubah")

        detail = next((d for d in krs.details if d.kode_mk == kode_mk), None)
        if detail is None:
            raise KRSError(f"{kode_mk} tidak ada di KRS")

        krs.details.remove(detail)  # delete-orphan
        # Sentuh diubah_pada agar baris krs di-update dan version naik (Slide 4)
        krs.diubah_pada = datetime.now(timezone.utc)
        self.db.commit()

    def validate_krs(self, nim: str) -> list[ValidationResult]:
        """Menjalankan validasi menyeluruh terhadap semua mata kuliah di kartu KRS mahasiswa (kosong jika semua valid)."""
        krs = self._krs_terkunci(nim)
        return self._validate_krs_obj(krs)

    def submit_krs(self, nim: str, requester_nim: str | None = None) -> KRS:
        """Periksa semuanya, baru pindah state dari DRAFT/REVISION menjadi SUBMITTED (Slide 2)."""
        try:
            krs = self._krs_terkunci(nim)
            self._cek_kepemilikan_mahasiswa(krs, requester_nim)
            krs.cek_transisi(KRSStatus.SUBMITTED, Actor.MAHASISWA)  # 409

            if not krs.details:
                raise KRSError("KRS kosong: tambahkan minimal satu mata kuliah")

            gagal = self._validate_krs_obj(krs)  # semua aturan, semua MK
            if gagal:
                pesan_gabungan = "; ".join(r.message for r in gagal)
                raise KRSError(f"Validasi KRS gagal sebelum submit: {pesan_gabungan}")

            krs.transition(KRSStatus.SUBMITTED, actor=Actor.MAHASISWA)
            krs.submitted_at = datetime.now(timezone.utc)
            logger.info("KRS submitted: nim=%s semester=%s", krs.nim, krs.semester)
            self.db.commit()
            return krs
        except StaleDataError as exc:
            self.db.rollback()
            raise TransitionError("KRS sudah berubah, muat ulang", status_code=409) from exc
        except Exception:
            self.db.rollback()
            raise

    def approve_krs(
        self,
        nim: str,
        dosen_pa_id: int,
        version: int | None = None,
    ) -> KRS:
        """Approve = satu unit kerja ACID: transisi APPROVED + approved_at + KRSLog + Notifikasi (Slide 3)."""
        try:
            krs = self._krs_terkunci(nim)
            self._cek_kepemilikan_dosen_pa(krs, dosen_pa_id)
            self._cek_versi_krs(krs, version)

            krs.transition(
                KRSStatus.APPROVED, actor=Actor.DOSEN_PA, dosen_id=dosen_pa_id
            )
            krs.approved_at = datetime.now(timezone.utc)
            if krs.id is None:
                self.db.flush()

            self.db.add(KRSLog(krs_id=krs.id, aksi="approve", oleh=dosen_pa_id))
            self.db.add(Notifikasi(nim=nim, pesan="KRS Anda disetujui"))
            logger.info(
                "KRS approved: nim=%s semester=%s dosen_pa_id=%s approved_at=%s",
                krs.nim,
                krs.semester,
                dosen_pa_id,
                krs.approved_at.isoformat() if krs.approved_at else None,
            )
            self.db.commit()  # semua atau tidak sama sekali
            return krs
        except StaleDataError as exc:
            self.db.rollback()
            raise TransitionError("KRS sudah berubah, muat ulang", status_code=409) from exc
        except Exception:
            self.db.rollback()
            raise

    def revise_krs(
        self,
        nim: str,
        dosen_pa_id: int,
        catatan: str,
        version: int | None = None,
    ) -> KRS:
        """Menolak/meminta revisi KRS oleh Dosen PA (SUBMITTED -> REVISION) dengan pola transaksi ACID yang sama."""
        try:
            krs = self._krs_terkunci(nim)
            self._cek_kepemilikan_dosen_pa(krs, dosen_pa_id)
            self._cek_versi_krs(krs, version)

            krs.transition(
                KRSStatus.REVISION,
                actor=Actor.DOSEN_PA,
                dosen_id=dosen_pa_id,
                catatan=catatan,
            )
            if krs.id is None:
                self.db.flush()

            self.db.add(KRSLog(krs_id=krs.id, aksi="revise", oleh=dosen_pa_id))
            self.db.add(
                Notifikasi(
                    nim=nim,
                    pesan=f"KRS Anda perlu direvisi: {krs.catatan_revisi}",
                )
            )
            logger.info(
                "KRS revised: nim=%s semester=%s dosen_pa_id=%s catatan=%s",
                krs.nim,
                krs.semester,
                dosen_pa_id,
                krs.catatan_revisi,
            )
            self.db.commit()
            return krs
        except StaleDataError as exc:
            self.db.rollback()
            raise TransitionError("KRS sudah berubah, muat ulang", status_code=409) from exc
        except Exception:
            self.db.rollback()
            raise
