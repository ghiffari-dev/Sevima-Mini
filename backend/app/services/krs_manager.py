from __future__ import annotations

import logging
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.krs import (
    Actor,
    KRS,
    KRSDetail,
    KRSError,
    KRSForbiddenError,
    KRSStatus,
    MataKuliah,
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
    """Satu pintu untuk semua perubahan KRS (Slide 4 & Slide 5)."""

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
            raise KRSForbiddenError(
                "Approve/revise hanya boleh dilakukan oleh Dosen PA mahasiswa ini"
            )

    def _validate_krs_obj(self, krs: KRS) -> list[ValidationResult]:
        """Menjalankan chain validator untuk setiap mata kuliah di kartu KRS."""
        results: list[ValidationResult] = []
        accumulated_details: list[KRSDetail] = []
        for d in krs.details:
            ctx = KRSContext(krs.nim, krs.semester, list(accumulated_details), d.matakuliah, self.db)
            res = self.chain.validate(ctx)
            results.append(res)
            if not res.ok:
                break
            accumulated_details.append(d)
        return results

    def add_course(
        self, nim: str, kode_mk: str, requester_nim: str | None = None
    ) -> KRSDetail:
        """Menambahkan 1 mata kuliah ke kartu KRS (hanya saat status DRAFT atau REVISION)."""
        krs = self._krs_terkunci(nim)
        self._cek_kepemilikan_mahasiswa(krs, requester_nim)
        if krs.status not in EDITABLE:
            raise TransitionError(f"KRS {krs.status.value} tidak bisa diubah")

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
        self.db.commit()  # satu transaksi · kunci dilepas
        return detail

    def remove_course(
        self, nim: str, kode_mk: str, requester_nim: str | None = None
    ) -> None:
        """Menghapus 1 mata kuliah dari kartu KRS (hanya saat status DRAFT atau REVISION)."""
        krs = self._krs_terkunci(nim)
        self._cek_kepemilikan_mahasiswa(krs, requester_nim)
        if krs.status not in EDITABLE:
            raise TransitionError("KRS tidak bisa diubah")

        detail = next((d for d in krs.details if d.kode_mk == kode_mk), None)
        if detail is None:
            raise KRSError(f"{kode_mk} tidak ada di KRS")

        krs.details.remove(detail)  # delete-orphan
        self.db.commit()

    def validate_krs(self, nim: str) -> list[ValidationResult]:
        """Menjalankan validasi menyeluruh terhadap mata kuliah di kartu KRS mahasiswa."""
        krs = self._krs_terkunci(nim)
        return self._validate_krs_obj(krs)

    def submit_krs(self, nim: str, requester_nim: str | None = None) -> KRS:
        """Mengajukan kartu KRS dari DRAFT/REVISION menjadi SUBMITTED setelah lolos validasi."""
        krs = self._krs_terkunci(nim)
        self._cek_kepemilikan_mahasiswa(krs, requester_nim)
        krs.cek_transisi(KRSStatus.SUBMITTED, Actor.MAHASISWA)

        if not krs.details:
            raise KRSError("KRS kosong tidak dapat di-submit")

        for res in self._validate_krs_obj(krs):
            if not res.ok:
                raise KRSError(f"Validasi KRS gagal sebelum submit: {res.message}")

        krs.transition(KRSStatus.SUBMITTED, actor=Actor.MAHASISWA)
        logger.info("KRS submitted: nim=%s semester=%s", krs.nim, krs.semester)
        self.db.commit()
        return krs

    def approve_krs(self, nim: str, dosen_pa_id: int) -> KRS:
        """Menyetujui kartu KRS oleh Dosen PA (SUBMITTED -> APPROVED) beserta waktu & log."""
        krs = self._krs_terkunci(nim)
        self._cek_kepemilikan_dosen_pa(krs, dosen_pa_id)
        krs.transition(KRSStatus.APPROVED, actor=Actor.DOSEN_PA, dosen_id=dosen_pa_id)
        logger.info(
            "KRS approved: nim=%s semester=%s dosen_pa_id=%s approved_at=%s",
            krs.nim,
            krs.semester,
            dosen_pa_id,
            krs.approved_at.isoformat() if krs.approved_at else None,
        )
        self.db.commit()
        return krs

    def revise_krs(self, nim: str, dosen_pa_id: int, catatan: str) -> KRS:
        """Menolak/meminta revisi kartu KRS oleh Dosen PA (SUBMITTED -> REVISION) dengan catatan wajib."""
        krs = self._krs_terkunci(nim)
        self._cek_kepemilikan_dosen_pa(krs, dosen_pa_id)
        krs.transition(
            KRSStatus.REVISION,
            actor=Actor.DOSEN_PA,
            dosen_id=dosen_pa_id,
            catatan=catatan,
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
