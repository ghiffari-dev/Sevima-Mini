from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Mapping, Sequence

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.grade import SkalaNilai
from app.models.krs import KRS, KRSDetail, MataKuliah

TWO_DECIMALS = Decimal("0.01")


@dataclass(frozen=True)
class Skala:
    """Representasi immutable satu entri skala nilai (bobot Decimal dan status kelulusan)."""

    bobot: Decimal
    lulus: bool


@dataclass(frozen=True)
class NilaiRecord:
    """Record nilai murni tanpa ketergantungan ORM/DB untuk perhitungan IPS & IPK."""

    kode_mk: str
    semester: str
    sks: int
    huruf: str


def _quantize_gpa(value: Decimal) -> Decimal:
    """Membulatkan nilai indeks prestasi sekali di akhir dengan ROUND_HALF_UP (2 desimal)."""
    return value.quantize(TWO_DECIMALS, rounding=ROUND_HALF_UP)


def rata(records: Sequence[NilaiRecord], skala: Mapping[str, Skala]) -> Decimal:
    """Menghitung rata-rata berbobot SKS dalam Decimal dan membulatkan sekali di akhir.

    Mengembalikan Decimal("0.00") apabila total SKS bernilai nol (mis. mahasiswa semester awal).
    """
    total_sks = sum(r.sks for r in records)
    if total_sks == 0:
        return Decimal("0.00")

    total_mutu = sum(
        (Decimal(str(skala[r.huruf].bobot)) * Decimal(r.sks) for r in records),
        Decimal("0"),
    )
    return _quantize_gpa(total_mutu / Decimal(total_sks))


def hitung_ips(
    records: Sequence[NilaiRecord],
    semester: str,
    skala: Mapping[str, Skala],
) -> Decimal:
    """Menghitung IPS satu semester dari seluruh mata kuliah bernilai pada semester tersebut (termasuk D & E)."""
    sem_records = [r for r in records if r.semester == semester]
    return rata(sem_records, skala)


def hitung_ipk(
    records: Sequence[NilaiRecord],
    skala: Mapping[str, Skala],
) -> Decimal:
    """Menghitung IPK kumulatif: ambil bobot terbaik per kode_mk dulu, lalu saring yang lulus."""
    terbaik: dict[str, NilaiRecord] = {}
    for record in records:
        current = terbaik.get(record.kode_mk)
        if current is None:
            terbaik[record.kode_mk] = record
            continue
        bobot_baru = Decimal(str(skala[record.huruf].bobot))
        bobot_lama = Decimal(str(skala[current.huruf].bobot))
        if bobot_baru > bobot_lama:
            terbaik[record.kode_mk] = record

    lulus_records = [r for r in terbaik.values() if skala[r.huruf].lulus]
    return rata(lulus_records, skala)


class NilaiRepo:
    """Repository tipis yang mengambil record nilai & skala_nilai dari database untuk GPACalculator."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def records(self, nim: str) -> list[NilaiRecord]:
        """Mengambil seluruh nilai terisi milik mahasiswa dalam satu query join."""
        stmt = (
            select(
                KRSDetail.kode_mk,
                KRS.semester,
                MataKuliah.sks,
                KRSDetail.nilai,
            )
            .join(KRS, KRSDetail.krs_id == KRS.id)
            .join(MataKuliah, KRSDetail.kode_mk == MataKuliah.kode_mk)
            .where(
                KRS.nim == nim,
                KRSDetail.nilai.is_not(None),
            )
            .order_by(KRS.semester.asc(), KRSDetail.id.asc())
        )
        rows = self.db.execute(stmt).all()
        return [
            NilaiRecord(
                kode_mk=str(kode_mk),
                semester=str(semester),
                sks=int(sks),
                huruf=str(huruf),
            )
            for kode_mk, semester, sks, huruf in rows
        ]

    def skala(self) -> dict[str, Skala]:
        """Membaca tabel skala_nilai menjadi kamus Skala dengan konversi Decimal dari string."""
        rows = self.db.scalars(select(SkalaNilai)).all()
        return {
            row.huruf: Skala(
                bobot=Decimal(str(row.bobot)),
                lulus=bool(row.lulus),
            )
            for row in rows
        }


class GPACalculator:
    """Layanan hitung-saat-dibaca (compute-on-read) untuk IPS & IPK berbasis NilaiRepo dan fungsi murni."""

    def __init__(self, repo: NilaiRepo) -> None:
        self.repo = repo

    @classmethod
    def from_session(cls, db: Session) -> "GPACalculator":
        """Helper konstruktor dari SQLAlchemy Session."""
        return cls(NilaiRepo(db))

    def calculate_ips(self, nim: str, semester: str) -> Decimal:
        """Menghitung IPS mahasiswa pada semester tertentu secara compute-on-read."""
        return hitung_ips(self.repo.records(nim), semester, self.repo.skala())

    def calculate_ipk(self, nim: str) -> Decimal:
        """Menghitung IPK mahasiswa secara compute-on-read."""
        return hitung_ipk(self.repo.records(nim), self.repo.skala())


def calculate_ipk_sql(db: Session, nim: str) -> Decimal:
    """Versi SQL CTE + Window Function ROW_NUMBER() sebagai pembanding differential testing."""
    sql = text(
        """
        WITH terbaik AS (
            SELECT
                kd.kode_mk,
                mk.sks,
                sn.bobot,
                sn.lulus,
                ROW_NUMBER() OVER (
                    PARTITION BY kd.kode_mk
                    ORDER BY sn.bobot DESC, sn.lulus DESC
                ) AS rn
            FROM krs_detail kd
            JOIN krs k ON kd.krs_id = k.id
            JOIN matakuliah mk ON kd.kode_mk = mk.kode_mk
            JOIN skala_nilai sn ON kd.nilai = sn.huruf
            WHERE k.nim = :nim AND kd.nilai IS NOT NULL
        )
        SELECT
            CAST(SUM(bobot * sks) AS REAL) / NULLIF(SUM(sks), 0) AS ipk_raw,
            SUM(bobot * sks) AS total_mutu,
            NULLIF(SUM(sks), 0) AS total_sks
        FROM terbaik
        WHERE rn = 1 AND lulus = 1
        """
    )
    row = db.execute(sql, {"nim": nim}).first()
    if row is None or row.total_sks is None or row.total_mutu is None:
        return Decimal("0.00")
    total_mutu = Decimal(str(row.total_mutu))
    total_sks = Decimal(str(row.total_sks))
    return _quantize_gpa(total_mutu / total_sks)
