from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import time
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.krs import KRS, KRSDetail, KRSStatus, MataKuliah
from app.services.krs_validator import (
    KRSContext,
    MIN_PASSING_WEIGHT,
    build_chain,
    default_validators,
    prasyarat_belum_lulus,
    resolve_grade_weight,
)


@dataclass(frozen=True)
class CourseOffering:
    """Representasi penawaran kelas mata kuliah untuk CSP recommender."""

    kode_mk: str
    nama: str
    sks: int
    hari: int
    jam_mulai: time
    jam_selesai: time
    kelas: str = "A"
    wajib: bool = True
    prasyarat: list[str] | None = None


@dataclass
class RecommendationResult:
    """Hasil rekomendasi KRS tervalidasi dari CSP solver."""

    selected: list[CourseOffering]
    total_sks: int
    skipped: list[str]
    validated: bool


def _is_conflict(a: CourseOffering, b: CourseOffering) -> bool:
    """Mengembalikan True jika dua penawaran kelas bentrok hari dan irisan jam."""
    if a.hari != b.hari:
        return False
    return a.jam_mulai < b.jam_selesai and b.jam_mulai < a.jam_selesai


def _fetch_passed_codes(db: Session, nim: str, semester: str) -> set[str]:
    """Mengambil kode MK yang sudah lulus (>= C) pada semester sebelumnya dari DB."""
    if not nim:
        return set()
    stmt = (
        select(KRSDetail.kode_mk, KRSDetail.nilai)
        .join(KRS, KRSDetail.krs_id == KRS.id)
        .where(
            KRS.nim == nim,
            KRS.semester < semester,
            KRS.status == KRSStatus.APPROVED,
            KRSDetail.nilai.is_not(None),
        )
    )
    rows = db.execute(stmt).all()
    return {
        kode
        for kode, nilai in rows
        if resolve_grade_weight(None, nilai) >= MIN_PASSING_WEIGHT
    }


def _to_matakuliah(offering: CourseOffering, db_mk_map: dict[str, MataKuliah]) -> MataKuliah:
    """Mengambil instance MataKuliah dari DB jika ada, atau membuat objek transient di memori."""
    if offering.kode_mk in db_mk_map:
        db_mk = db_mk_map[offering.kode_mk]
        slots = db_mk.get_jadwal_slots()
        if (
            slots
            and (offering.hari, offering.jam_mulai, offering.jam_selesai) in slots
            and db_mk.sks == offering.sks
        ):
            return db_mk
        mk = MataKuliah(
            kode_mk=offering.kode_mk,
            nama=offering.nama,
            sks=offering.sks,
            hari=offering.hari,
            jam_mulai=offering.jam_mulai,
            jam_selesai=offering.jam_selesai,
        )
        mk.prasyarat = list(db_mk.prasyarat)
        return mk

    return MataKuliah(
        kode_mk=offering.kode_mk,
        nama=offering.nama,
        sks=offering.sks,
        hari=offering.hari,
        jam_mulai=offering.jam_mulai,
        jam_selesai=offering.jam_selesai,
    )


def recommend_krs_csp(
    offerings: list[CourseOffering],
    max_sks: int = 24,
    lulus_codes: set[str] | None = None,
    db: Session | None = None,
    nim: str = "",
    semester: str = "20251",
) -> RecommendationResult:
    """Menyusun rekomendasi KRS bebas bentrok dengan CSP backtracking (prioritas wajib > pilihan)
    dan memverifikasi hasil akhir melalui Chain of Responsibility (`default_validators`).
    """
    if max_sks <= 0 or not offerings:
        return RecommendationResult(selected=[], total_sks=0, skipped=[], validated=True)

    db_mk_map: dict[str, MataKuliah] = {}
    if db is not None:
        all_codes = list({o.kode_mk for o in offerings})
        if all_codes:
            stmt_mks = (
                select(MataKuliah)
                .where(MataKuliah.kode_mk.in_(all_codes))
                .options(selectinload(MataKuliah.prasyarat))
            )
            for mk in db.scalars(stmt_mks).all():
                db_mk_map[mk.kode_mk] = mk

    if lulus_codes is not None:
        passed_codes = set(lulus_codes)
    elif db is not None:
        passed_codes = _fetch_passed_codes(db, nim, semester)
    else:
        passed_codes = set()

    # Kelompokkan penawaran paralel per kode_mk dengan tetap menjaga urutan prioritas
    grouped: dict[str, list[CourseOffering]] = defaultdict(list)
    ordered_codes: list[str] = []
    for off in offerings:
        if off.kode_mk not in grouped:
            ordered_codes.append(off.kode_mk)
        grouped[off.kode_mk].append(off)

    skipped_codes: list[str] = []
    eligible_groups: list[tuple[str, bool, list[CourseOffering]]] = []

    for kode in ordered_codes:
        group = grouped[kode]
        sample = group[0]

        # Cek prasyarat dari dataclass CourseOffering maupun dari relasi DB
        prereq_ok = True
        if sample.prasyarat:
            if any(req not in passed_codes for req in sample.prasyarat):
                prereq_ok = False
        if prereq_ok and db is not None and kode in db_mk_map:
            belum = prasyarat_belum_lulus(
                db, nim, kode, semester, mk_obj=db_mk_map[kode]
            )
            if belum:
                prereq_ok = False

        valid_offerings = [
            o for o in group if 1 <= o.sks <= max_sks and o.jam_mulai < o.jam_selesai
        ]
        if not prereq_ok or not valid_offerings:
            skipped_codes.append(kode)
            continue

        is_wajib = any(o.wajib for o in valid_offerings)
        eligible_groups.append((kode, is_wajib, valid_offerings))

    # Urutkan variabel CSP: MK wajib diprioritaskan di depan MK pilihan
    eligible_groups.sort(key=lambda item: (0 if item[1] else 1))

    n = len(eligible_groups)
    suffix_wajib = [0] * (n + 1)
    suffix_sks = [0] * (n + 1)
    for i in range(n - 1, -1, -1):
        _, is_wajib, opts = eligible_groups[i]
        suffix_wajib[i] = suffix_wajib[i + 1] + (1 if is_wajib else 0)
        suffix_sks[i] = suffix_sks[i + 1] + max(o.sks for o in opts)

    best_score: tuple[int, int, int] = (-1, -1, -1)
    best_selection: list[CourseOffering] = []
    nodes_visited = 0
    max_nodes = 50000

    def backtrack(
        idx: int,
        chosen: list[CourseOffering],
        cur_wajib: int,
        cur_sks: int,
    ) -> None:
        nonlocal best_score, best_selection, nodes_visited
        nodes_visited += 1
        if nodes_visited > max_nodes:
            return

        score = (cur_wajib, cur_sks, len(chosen))
        if score > best_score:
            best_score = score
            best_selection = list(chosen)

        if idx >= n:
            return

        # Branch-and-bound pruning agar optimal dan cepat
        max_possible_wajib = cur_wajib + suffix_wajib[idx]
        if max_possible_wajib < best_score[0]:
            return
        max_possible_sks = min(max_sks, cur_sks + suffix_sks[idx])
        if max_possible_wajib == best_score[0] and max_possible_sks < best_score[1]:
            return

        _, is_wajib, opts = eligible_groups[idx]
        for cand in opts:
            if cur_sks + cand.sks > max_sks:
                continue
            if any(_is_conflict(cand, prev) for prev in chosen):
                continue
            chosen.append(cand)
            backtrack(
                idx + 1,
                chosen,
                cur_wajib + (1 if (is_wajib or cand.wajib) else 0),
                cur_sks + cand.sks,
            )
            chosen.pop()

        # Opsi skip variabel MK ini jika bentrok atau melebihi batas SKS
        backtrack(idx + 1, chosen, cur_wajib, cur_sks)

    backtrack(0, [], 0, 0)

    selected_codes = {o.kode_mk for o in best_selection}
    for kode, _, _ in eligible_groups:
        if kode not in selected_codes:
            skipped_codes.append(kode)

    # Guardrail: validate_krs (Chain of Responsibility) memutuskan kelayakan akhir sebelum dikembalikan
    chain = build_chain(default_validators())
    validated_details: list[KRSDetail] = []
    final_selected: list[CourseOffering] = []
    all_valid = True

    for off in best_selection:
        mk_obj = _to_matakuliah(off, db_mk_map)
        ctx = KRSContext(
            nim=nim or "SIMULASI",
            semester=semester,
            details=list(validated_details),
            mk_baru=mk_obj,
            db=db,
        )
        res = chain.validate(ctx)
        if res.ok:
            validated_details.append(KRSDetail(kode_mk=mk_obj.kode_mk, matakuliah=mk_obj))
            final_selected.append(off)
        else:
            all_valid = False
            skipped_codes.append(off.kode_mk)

    total_sks = sum(o.sks for o in final_selected)
    return RecommendationResult(
        selected=final_selected,
        total_sks=total_sks,
        skipped=skipped_codes,
        validated=all_valid and total_sks <= max_sks,
    )
