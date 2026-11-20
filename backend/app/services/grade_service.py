from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import Any, Protocol

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.calon_mahasiswa import CalonMahasiswa
from app.models.grade import (
    AlasanWajibError,
    GradeForbiddenError,
    GradeHistory,
    GradeNotFoundError,
    HurufTidakValidError,
    PresensiKurangError,
    SkalaNilai,
    ensure_riwayat_nilai_view,
    seed_skala_nilai,
)
from app.models.jalur_masuk import JalurMasuk
from app.models.krs import KRS, KRSDetail, KRSStatus, MataKuliah
from app.models.program_studi import ProgramStudi
from app.models.schedule import Dosen as DosenJadwal, Jadwal, Kelas as KelasJadwal, Ruangan

MIN_PRESENSI = Decimal("75")


class PresensiPort(Protocol):
    """Port Dependency Inversion untuk membaca persentase kehadiran mahasiswa di kelas."""

    def persentase(self, nim: str, kelas_id: int) -> Decimal: ...


class StubPresensiPort:
    """Implementasi stub berbasis kamus memori sebelum modul presensi dibangun di Minggu 12."""

    def __init__(
        self,
        data: dict[tuple[str, int], Decimal | int | str] | None = None,
        default_persen: Decimal | int | str = Decimal("100.00"),
    ) -> None:
        self._data: dict[tuple[str, int], Decimal] = {
            k: Decimal(str(v)) for k, v in (data or {}).items()
        }
        self._default = Decimal(str(default_persen))

    def set_persentase(
        self, nim: str, kelas_id: int, nilai: Decimal | int | str
    ) -> None:
        """Menetapkan persentase kehadiran dummy untuk pasangan (nim, kelas_id)."""
        self._data[(nim, int(kelas_id))] = Decimal(str(nilai))

    def persentase(self, nim: str, kelas_id: int) -> Decimal:
        """Mengembalikan persentase presensi mahasiswa pada kelas tertentu."""
        return self._data.get((nim, int(kelas_id)), self._default)


default_presensi_stub = StubPresensiPort()


@dataclass(frozen=True)
class InputNilaiResult:
    """Hasil operasi GradeService.input_nilai untuk dikonsumsi router & test."""

    detail: KRSDetail
    history: GradeHistory | None
    changed: bool
    nilai_lama: str | None
    nilai_baru: str
    presensi_persen: Decimal
    nim: str
    kelas_id: int
    semester: str


class GradeService:
    """Layanan satu pintu untuk input/ubah nilai oleh dosen pengampu beserta audit trail atomik."""

    def __init__(self, db: Session, presensi: PresensiPort) -> None:
        self.db = db
        self.presensi = presensi

    def is_pengampu(self, kelas_id: int, dosen_id: int) -> bool:
        """Memeriksa apakah dosen_id tercatat sebagai pengampu kelas_id pada tabel jadwal."""
        stmt = (
            select(Jadwal.id)
            .where(Jadwal.kelas_id == kelas_id, Jadwal.dosen_id == dosen_id)
            .limit(1)
        )
        return self.db.scalars(stmt).first() is not None

    def input_nilai(
        self,
        dosen_id: int,
        kelas_id: int,
        nim: str,
        huruf: str,
        alasan: str | None = None,
    ) -> InputNilaiResult:
        """Menetapkan atau mengubah nilai mahasiswa dalam 1 transaksi atomik beserta grade_history."""
        # 1. Penjaga pertama: wajib dosen pengampu (403 sebelum membaca data mahasiswa)
        if not self.is_pengampu(kelas_id, dosen_id):
            raise GradeForbiddenError(
                "Hanya dosen pengampu kelas ini yang diizinkan mengisi nilai"
            )

        # 2. Ambil & kunci baris KRSDetail (pessimistic lock) -> 404 jika tidak ditemukan
        stmt_detail = (
            select(KRSDetail, KRS.semester)
            .join(KRS, KRSDetail.krs_id == KRS.id)
            .where(KRSDetail.kelas_id == kelas_id, KRS.nim == nim)
            .with_for_update()
        )
        row = self.db.execute(stmt_detail).first()
        if row is None:
            raise GradeNotFoundError(
                f"Mahasiswa {nim} tidak terdaftar pada kelas ID {kelas_id}"
            )
        detail, semester = row[0], str(row[1])

        # 3. Penjaga kedua: presensi minimal 75% (tepat 75% diizinkan)
        kehadiran = Decimal(str(self.presensi.persentase(nim, kelas_id)))
        if kehadiran < MIN_PRESENSI:
            raise PresensiKurangError(
                f"Nilai tidak dapat diinput karena presensi mahasiswa {nim} adalah {kehadiran}% (< {MIN_PRESENSI}%)"
            )

        # 4. Validasi huruf terhadap sumber kebenaran tabel skala_nilai
        huruf_clean = huruf.strip().upper()
        skala = self.db.get(SkalaNilai, huruf_clean)
        if skala is None:
            raise HurufTidakValidError(
                f"Huruf nilai '{huruf}' tidak terdaftar pada tabel skala_nilai"
            )

        # 5. Idempoten jika huruf sama dengan yang sudah tersimpan
        if detail.nilai == huruf_clean:
            return InputNilaiResult(
                detail=detail,
                history=None,
                changed=False,
                nilai_lama=detail.nilai,
                nilai_baru=huruf_clean,
                presensi_persen=kehadiran,
                nim=nim,
                kelas_id=kelas_id,
                semester=semester,
            )

        # 6. Jika nilai sudah pernah diisi, alasan perubahan wajib ada
        nilai_lama = detail.nilai
        alasan_clean = alasan.strip() if alasan and alasan.strip() else None
        if nilai_lama is not None and not alasan_clean:
            raise AlasanWajibError(
                "Alasan perubahan wajib diisi ketika mengubah nilai yang sudah tersimpan"
            )

        # 7. Satu transaksi atomik: tambah grade_history + ubah krs_detail.nilai
        history = GradeHistory(
            grade_id=detail.id,
            nilai_lama=nilai_lama,
            nilai_baru=huruf_clean,
            diubah_oleh=dosen_id,
            diubah_pada=datetime.now(timezone.utc),
            alasan=alasan_clean,
        )
        try:
            self.db.add(history)
            detail.nilai = huruf_clean
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

        self.db.refresh(detail)
        self.db.refresh(history)
        return InputNilaiResult(
            detail=detail,
            history=history,
            changed=True,
            nilai_lama=nilai_lama,
            nilai_baru=huruf_clean,
            presensi_persen=kehadiran,
            nim=nim,
            kelas_id=kelas_id,
            semester=semester,
        )

    def list_kelas_pengampu(self, dosen_id: int) -> list[dict[str, Any]]:
        """Mengembalikan daftar kelas yang diampu oleh dosen tertentu."""
        stmt = (
            select(KelasJadwal, MataKuliah)
            .join(MataKuliah, KelasJadwal.kode_mk == MataKuliah.kode_mk)
            .join(Jadwal, Jadwal.kelas_id == KelasJadwal.id)
            .where(Jadwal.dosen_id == dosen_id)
            .distinct()
            .order_by(KelasJadwal.semester.desc(), KelasJadwal.kode_mk.asc())
        )
        rows = self.db.execute(stmt).all()
        result: list[dict[str, Any]] = []
        for kls, mk in rows:
            peserta_count = len(
                self.db.scalars(
                    select(KRSDetail.id).where(KRSDetail.kelas_id == kls.id)
                ).all()
            )
            result.append(
                {
                    "kelas_id": kls.id,
                    "kode_mk": kls.kode_mk,
                    "nama_mk": mk.nama,
                    "nama_kelas": kls.nama_kelas,
                    "sks": mk.sks,
                    "semester": kls.semester,
                    "jumlah_peserta": peserta_count,
                }
            )
        return result

    def list_peserta_kelas(
        self, kelas_id: int, dosen_id: int
    ) -> dict[str, Any]:
        """Mengembalikan daftar peserta kelas beserta persentase presensi & nilai saat ini."""
        kls = self.db.get(KelasJadwal, kelas_id)
        if kls is None:
            raise GradeNotFoundError(f"Kelas ID {kelas_id} tidak ditemukan")
        if not self.is_pengampu(kelas_id, dosen_id):
            raise GradeForbiddenError(
                "Hanya dosen pengampu yang dapat melihat daftar nilai kelas ini"
            )

        mk = self.db.get(MataKuliah, kls.kode_mk)
        stmt = (
            select(KRSDetail, KRS, CalonMahasiswa)
            .join(KRS, KRSDetail.krs_id == KRS.id)
            .join(CalonMahasiswa, KRS.nim == CalonMahasiswa.nim)
            .where(KRSDetail.kelas_id == kelas_id)
            .order_by(KRS.nim.asc())
        )
        rows = self.db.execute(stmt).all()
        peserta: list[dict[str, Any]] = []
        for detail, krs, mhs in rows:
            persen = Decimal(str(self.presensi.persentase(mhs.nim, kelas_id)))
            bisa_diinput = persen >= MIN_PRESENSI
            peserta.append(
                {
                    "nim": mhs.nim,
                    "nama": mhs.nama_lengkap,
                    "semester": krs.semester,
                    "nilai": detail.nilai,
                    "presensi_persen": f"{persen.quantize(Decimal('0.01'))}",
                    "bisa_diinput": bisa_diinput,
                    "alasan_blokir": (
                        None
                        if bisa_diinput
                        else f"Presensi {persen}% di bawah batas minimal {MIN_PRESENSI}%"
                    ),
                }
            )
        return {
            "kelas_id": kls.id,
            "kode_mk": kls.kode_mk,
            "nama_mk": mk.nama if mk is not None else kls.kode_mk,
            "nama_kelas": kls.nama_kelas,
            "sks": mk.sks if mk is not None else 0,
            "semester": kls.semester,
            "peserta": peserta,
        }

    def get_riwayat_nilai(self, nim: str) -> list[dict[str, Any]]:
        """Mengambil riwayat perubahan nilai satu mahasiswa lewat SQL View `riwayat_nilai`."""
        ensure_riwayat_nilai_view(self.db)
        rows = self.db.execute(
            text(
                """
                SELECT
                    id,
                    grade_id,
                    nim,
                    semester,
                    kode_mk,
                    nama_mk,
                    kelas_id,
                    nilai_lama,
                    nilai_baru,
                    diubah_oleh,
                    nama_dosen,
                    diubah_pada,
                    alasan
                FROM riwayat_nilai
                WHERE nim = :nim
                ORDER BY id ASC
                """
            ),
            {"nim": nim},
        ).mappings().all()
        items: list[dict[str, Any]] = []
        for r in rows:
            ts = r["diubah_pada"]
            ts_str = ts.isoformat() if isinstance(ts, datetime) else str(ts)
            items.append(
                {
                    "id": int(r["id"]),
                    "grade_id": int(r["grade_id"]),
                    "nim": str(r["nim"]),
                    "semester": str(r["semester"]),
                    "kode_mk": str(r["kode_mk"]),
                    "nama_mk": str(r["nama_mk"]),
                    "kelas_id": int(r["kelas_id"]) if r["kelas_id"] is not None else None,
                    "nilai_lama": r["nilai_lama"],
                    "nilai_baru": str(r["nilai_baru"]),
                    "diubah_oleh": int(r["diubah_oleh"]),
                    "nama_dosen": str(r["nama_dosen"]),
                    "diubah_pada": ts_str,
                    "alasan": r["alasan"],
                }
            )
        return items

    def seed_demo_data(self) -> dict[str, Any]:
        """Menyiapkan skenario dummy Rina (presensi 90%) & Budi (presensi 70%) untuk demo UI."""
        seed_skala_nilai(self.db)
        ensure_riwayat_nilai_view(self.db)

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

        dummy_students = [
            ("2025001-0101", "Rina (Dummy)", "rina.demo@sevima.ac.id"),
            ("2025001-0102", "Budi (Dummy)", "budi.demo@sevima.ac.id"),
        ]
        for nim, nama, email in dummy_students:
            mhs = self.db.scalars(
                select(CalonMahasiswa).where(CalonMahasiswa.nim == nim)
            ).first()
            if mhs is None:
                self.db.add(
                    CalonMahasiswa(
                        nama_lengkap=nama,
                        email=email,
                        phone="081200001111",
                        tanggal_lahir=date(2005, 3, 15),
                        program_studi_id=prodi.id,
                        jalur_masuk_id=jalur.id,
                        status="approved",
                        nim=nim,
                    )
                )
        self.db.flush()

        room = self.db.get(Ruangan, "R201")
        if room is None:
            room = Ruangan(kode="R201", nama="Ruang R201", kapasitas=40, gedung="Gedung B")
            self.db.add(room)
            self.db.flush()

        dosen_pengampu = self.db.scalars(
            select(DosenJadwal).where(DosenJadwal.nidn == "00100101")
        ).first()
        if dosen_pengampu is None:
            dosen_pengampu = DosenJadwal(nidn="00100101", nama="Dr. Pengampu Demo")
            self.db.add(dosen_pengampu)
            self.db.flush()

        dosen_lain = self.db.scalars(
            select(DosenJadwal).where(DosenJadwal.nidn == "00100102")
        ).first()
        if dosen_lain is None:
            dosen_lain = DosenJadwal(nidn="00100102", nama="Dr. Non Pengampu")
            self.db.add(dosen_lain)
            self.db.flush()

        mk_specs = [
            ("MA101", "Kalkulus 1", 3),
            ("IF101", "Algoritma", 4),
            ("UN101", "Bahasa Inggris", 2),
            ("IF201", "Struktur Data", 3),
            ("IF202", "Basis Data", 3),
        ]
        for kode, nama, sks in mk_specs:
            if self.db.get(MataKuliah, kode) is None:
                self.db.add(MataKuliah(kode_mk=kode, nama=nama, sks=sks))
        self.db.flush()

        class_specs = [
            ("MA101", "A", "20241", 1, time(8, 0), time(10, 0)),
            ("IF101", "A", "20241", 2, time(8, 0), time(10, 0)),
            ("UN101", "A", "20241", 3, time(8, 0), time(10, 0)),
            ("MA101", "A", "20242", 1, time(10, 0), time(12, 0)),
            ("IF201", "A", "20242", 2, time(10, 0), time(12, 0)),
            ("IF202", "A", "20242", 3, time(10, 0), time(12, 0)),
        ]
        kelas_map: dict[tuple[str, str], KelasJadwal] = {}
        for kode_mk, nama_kls, sem, hari, mulai, selesai in class_specs:
            kls = self.db.scalars(
                select(KelasJadwal).where(
                    KelasJadwal.kode_mk == kode_mk,
                    KelasJadwal.nama_kelas == nama_kls,
                    KelasJadwal.semester == sem,
                )
            ).first()
            if kls is None:
                kls = KelasJadwal(
                    kode_mk=kode_mk, nama_kelas=nama_kls, kuota=40, semester=sem
                )
                self.db.add(kls)
                self.db.flush()
            existing_jadwal = self.db.scalars(
                select(Jadwal).where(Jadwal.kelas_id == kls.id)
            ).first()
            if existing_jadwal is None:
                self.db.add(
                    Jadwal(
                        kelas_id=kls.id,
                        ruangan_kode=room.kode,
                        dosen_id=dosen_pengampu.id,
                        hari=hari,
                        jam_mulai=mulai,
                        jam_selesai=selesai,
                    )
                )
            kelas_map[(kode_mk, sem)] = kls
        self.db.flush()

        def ensure_krs_detail(
            nim: str, sem: str, kode_mk: str, initial_nilai: str | None
        ) -> KRSDetail:
            krs = self.db.scalars(
                select(KRS).where(KRS.nim == nim, KRS.semester == sem)
            ).first()
            if krs is None:
                krs = KRS(
                    nim=nim,
                    semester=sem,
                    status=KRSStatus.APPROVED,
                    dosen_pa_id=dosen_pengampu.id,
                )
                self.db.add(krs)
                self.db.flush()
            kls = kelas_map[(kode_mk, sem)]
            detail = self.db.scalars(
                select(KRSDetail).where(
                    KRSDetail.krs_id == krs.id, KRSDetail.kode_mk == kode_mk
                )
            ).first()
            if detail is None:
                detail = KRSDetail(
                    krs_id=krs.id,
                    kode_mk=kode_mk,
                    kelas_id=kls.id,
                    nilai=initial_nilai,
                )
                self.db.add(detail)
                self.db.flush()
                if initial_nilai is not None:
                    self.db.add(
                        GradeHistory(
                            grade_id=detail.id,
                            nilai_lama=None,
                            nilai_baru=initial_nilai,
                            diubah_oleh=dosen_pengampu.id,
                            diubah_pada=datetime.now(timezone.utc),
                            alasan="Input awal skenario demo",
                        )
                    )
            return detail

        # Rina: semester 20241 (E, A, B -> IPS 2.44) & semester 20242 (B, C, D -> IPS 2.00, IPK 3.08)
        ensure_krs_detail("2025001-0101", "20241", "MA101", "E")
        ensure_krs_detail("2025001-0101", "20241", "IF101", "A")
        ensure_krs_detail("2025001-0101", "20241", "UN101", "B")
        ensure_krs_detail("2025001-0101", "20242", "MA101", "B")
        ensure_krs_detail("2025001-0101", "20242", "IF201", "C")
        ensure_krs_detail("2025001-0101", "20242", "IF202", "D")

        # Budi: terdaftar di semester 20242 pada Struktur Data & Basis Data (belum bernilai, presensi 70%)
        ensure_krs_detail("2025001-0102", "20242", "IF201", None)
        ensure_krs_detail("2025001-0102", "20242", "IF202", None)

        self.db.commit()

        # Set presensi stub untuk seluruh kelas demo: Rina 90%, Budi 70%
        if isinstance(self.presensi, StubPresensiPort):
            for kls in kelas_map.values():
                self.presensi.set_persentase("2025001-0101", kls.id, Decimal("90.00"))
                self.presensi.set_persentase("2025001-0102", kls.id, Decimal("70.00"))

        return {
            "detail": "Data demo modul nilai (Rina 90% & Budi 70%) berhasil dimuat.",
            "dosen_pengampu_id": dosen_pengampu.id,
            "kelas_ids": {f"{k}_{s}": v.id for (k, s), v in kelas_map.items()},
        }
