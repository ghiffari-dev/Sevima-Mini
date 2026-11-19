from __future__ import annotations

from datetime import time
from itertools import product

import pytest
from hypothesis import given, settings, strategies as st

from app.models.krs import Actor, KRS, KRSDetail, KRSStatus, MataKuliah, TransitionError
from app.services.krs_recommender import CourseOffering, recommend_krs_csp
from app.services.krs_validator import ConflictValidator, KRSContext, SKSValidator


daftar_sks = st.lists(st.integers(min_value=1, max_value=4), max_size=40)


@settings(max_examples=1000)
@given(daftar_sks)
def test_total_sks_tidak_pernah_lebih_dari_24(sks_list: list[int]) -> None:
    """Properti: urutan add_course apa pun tidak pernah membuat total SKS diterima > 24."""
    details: list[KRSDetail] = []
    for i, sks in enumerate(sks_list):
        mk = MataKuliah(
            kode_mk=f"MK{i:03d}",
            nama=f"MK {i}",
            sks=sks,
            hari=1,
            jam_mulai=time(8, 0),
            jam_selesai=time(10, 0),
        )
        total = sum(d.matakuliah.sks for d in details)
        ctx = KRSContext("2025001", "20251", details, mk, db=None)
        if SKSValidator().validate(ctx).ok:
            details.append(KRSDetail(kode_mk=mk.kode_mk, matakuliah=mk))
        else:
            assert total + sks > 24
    assert sum(d.matakuliah.sks for d in details) <= 24


jadwal = st.tuples(
    st.integers(1, 3),  # hari: Senin-Rabu
    st.integers(7, 16),  # jam mulai
    st.integers(1, 3),  # durasi (jam)
)


def slot(mk: MataKuliah) -> set[tuple[int, int]]:
    """Pemeriksa independen: memecah jadwal menjadi himpunan slot (hari, jam)."""
    return {(mk.hari, h) for h in range(mk.jam_mulai.hour, mk.jam_selesai.hour)}


@settings(max_examples=1000)
@given(st.lists(jadwal, max_size=12))
def test_mk_diterima_tidak_pernah_bentrok(daftar: list[tuple[int, int, int]]) -> None:
    """Properti: semua MK yang lolos ConflictValidator tidak memiliki irisan jadwal."""
    details: list[KRSDetail] = []
    for i, (hari, jam, durasi) in enumerate(daftar):
        mk = MataKuliah(
            kode_mk=f"MK{i}",
            nama=f"MK {i}",
            sks=2,
            hari=hari,
            jam_mulai=time(jam, 0),
            jam_selesai=time(jam + durasi, 0),
        )
        ctx = KRSContext("2025001", "20251", details, mk, db=None)
        if ConflictValidator().validate(ctx).ok:
            details.append(KRSDetail(kode_mk=mk.kode_mk, matakuliah=mk))

    slots = [slot(d.matakuliah) for d in details]
    assert sum(map(len, slots)) == len(set().union(*slots))


S, A = KRSStatus, Actor
SAH = {
    (S.DRAFT, S.SUBMITTED, A.MAHASISWA),
    (S.SUBMITTED, S.APPROVED, A.DOSEN_PA),
    (S.SUBMITTED, S.REVISION, A.DOSEN_PA),
    (S.REVISION, S.SUBMITTED, A.MAHASISWA),
}
ILEGAL = [p for p in product(S, S, A) if p not in SAH]


def test_jumlah_kombinasi_transisi_ilegal_adalah_28() -> None:
    """Memastikan ruang kombinasi 4x4x2=32 dikurangi 4 transisi sah menghasilkan 28 kasus ilegal."""
    assert len(ILEGAL) == 28


@pytest.mark.parametrize("asal,tujuan,aktor", ILEGAL)
def test_transisi_ilegal_ditolak(
    asal: KRSStatus, tujuan: KRSStatus, aktor: Actor
) -> None:
    """Semua 28 kombinasi transisi ilegal wajib memicu TransitionError tanpa mengubah status."""
    krs = KRS(nim="2025001-0001", semester="20251", status=asal, dosen_pa_id=10)
    krs.details.append(KRSDetail(kode_mk="IF101"))
    with pytest.raises(TransitionError):
        krs.transition(tujuan, aktor, dosen_id=10, catatan="Revisi")
    assert krs.status == asal


offering_strategy = st.lists(
    st.tuples(
        st.integers(1, 4),  # sks
        st.integers(1, 5),  # hari
        st.integers(7, 16),  # jam mulai
        st.integers(1, 3),  # durasi
        st.booleans(),  # wajib
    ),
    max_size=12,
)


@settings(max_examples=200)
@given(offering_strategy)
def test_recommender_csp_properti_bebas_bentrok_dan_sks_valid(
    items: list[tuple[int, int, int, int, bool]],
) -> None:
    """Properti CSP Recommender: hasil selalu tervalidasi, total SKS <= 24, dan bebas bentrok."""
    offerings = [
        CourseOffering(
            kode_mk=f"MK{i:02d}",
            nama=f"Mata Kuliah {i}",
            sks=sks,
            hari=hari,
            jam_mulai=time(jam, 0),
            jam_selesai=time(jam + durasi, 0),
            wajib=wajib,
        )
        for i, (sks, hari, jam, durasi, wajib) in enumerate(items)
    ]

    result = recommend_krs_csp(offerings, max_sks=24)
    assert result.validated is True
    assert result.total_sks <= 24
    assert sum(o.sks for o in result.selected) == result.total_sks

    slots = [
        {(o.hari, h) for h in range(o.jam_mulai.hour, o.jam_selesai.hour)}
        for o in result.selected
    ]
    assert sum(map(len, slots)) == len(set().union(*slots))
