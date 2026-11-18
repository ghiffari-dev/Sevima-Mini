from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.krs import (
    KRS,
    KRSDetail,
    KRSError,
    KRSStatus,
    MataKuliah,
    StateTransitionError,
    TRANSITIONS,
)
from app.services.krs_validator import (
    KRSContext,
    ValidationResult,
    Validator,
    build_chain,
    default_validators,
)

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
            .options(selectinload(KRS.details).selectinload(KRSDetail.matakuliah))
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

    def add_course(self, nim: str, kode_mk: str) -> KRSDetail:
        """Menambahkan 1 mata kuliah ke kartu KRS (hanya saat status DRAFT atau REVISION)."""
        krs = self._krs_terkunci(nim)
        if krs.status not in EDITABLE:
            raise KRSError(f"KRS {krs.status.value} tidak bisa diubah")

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

    def remove_course(self, nim: str, kode_mk: str) -> None:
        """Menghapus 1 mata kuliah dari kartu KRS (hanya saat status DRAFT atau REVISION)."""
        krs = self._krs_terkunci(nim)
        if krs.status not in EDITABLE:
            raise KRSError("KRS tidak bisa diubah")

        detail = next((d for d in krs.details if d.kode_mk == kode_mk), None)
        if detail is None:
            raise KRSError(f"{kode_mk} tidak ada di KRS")

        krs.details.remove(detail)  # delete-orphan
        self.db.commit()

    def validate_krs(self, nim: str) -> list[ValidationResult]:
        """Menjalankan validasi menyeluruh terhadap mata kuliah di kartu KRS mahasiswa."""
        krs = self._krs_terkunci(nim)
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

    def submit_krs(self, nim: str) -> KRS:
        """Mengajukan kartu KRS dari DRAFT/REVISION menjadi SUBMITTED melalui transition()."""
        krs = self._krs_terkunci(nim)
        krs.transition(KRSStatus.SUBMITTED, actor="mahasiswa")
        self.db.commit()
        return krs

    def approve_krs(self, nim: str, dosen_pa_id: int) -> KRS:
        """Menyetujui kartu KRS oleh Dosen PA (SUBMITTED -> APPROVED) melalui transition()."""
        krs = self._krs_terkunci(nim)
        krs.transition(KRSStatus.APPROVED, actor="dosen", dosen_id=dosen_pa_id)
        self.db.commit()
        return krs

    def revise_krs(self, nim: str, dosen_pa_id: int) -> KRS:
        """Menolak/meminta revisi kartu KRS oleh Dosen PA (SUBMITTED -> REVISION) melalui transition()."""
        krs = self._krs_terkunci(nim)
        krs.transition(KRSStatus.REVISION, actor="dosen", dosen_id=dosen_pa_id)
        self.db.commit()
        return krs
