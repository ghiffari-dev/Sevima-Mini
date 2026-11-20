from __future__ import annotations

from collections import deque
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json

from fastapi.testclient import TestClient
from hypothesis import given, settings as h_settings, strategies as st
import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.database import get_db as get_orm_db
from app.core.security import create_access_token
from app.main import app
from app.models.base import Base
from app.models.calon_mahasiswa import CalonMahasiswa
from app.models.finance import (
    Billing,
    BillingAlreadyPaidError,
    BillingStatus,
    InvalidPaymentAmountError,
    PaymentMethod,
    PaymentTransaction,
    seed_payment_methods,
)
from app.models.jalur_masuk import JalurMasuk
from app.models.krs import (
    KRS,
    KRSBillingBlockedError,
    KRSDetail,
    KRSStatus,
    MataKuliah,
    Notifikasi,
)
from app.models.program_studi import ProgramStudi
from app.models.schedule import Dosen as DosenJadwal, Jadwal, Kelas as KelasJadwal, Ruangan
from app.services import finance_ai_report
from app.services.billing_service import (
    BillingService,
    finance_notification_history,
)
from app.services.finance_ai_report import (
    generate_financial_insights,
    generate_financial_insights_from_csv,
)
from app.services.finance_calculator import (
    LateFeeConfig,
    PaymentCSVRow,
    calculate_late_fee,
    compute_webhook_signature,
    determine_billing_status,
    resolve_spp_amount,
    verify_webhook_signature,
)
from app.services.finance_scheduler import FinanceSchedulerManager
from app.services.krs_manager import KRSManager
from app.services.krs_validator import KRSContext, TunggakanValidator, build_chain
from app.services.schedule_observer import LogChannel, NotificationRecord
from app.services.schedule_recommender import FakeLLMClient


def _make_memory_session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_connection, connection_record):
        cur = dbapi_connection.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _seed_academic_base(db) -> dict[str, object]:
    prodi_ti = ProgramStudi(
        kode="001", nama="Teknik Informatika", fakultas="Fakultas Teknik"
    )
    prodi_ek = ProgramStudi(
        kode="002", nama="Akuntansi", fakultas="Fakultas Ekonomi"
    )
    prodi_khusus = ProgramStudi(
        kode="003",
        nama="Kedokteran",
        fakultas="Fakultas Kedokteran",
        biaya_spp=Decimal("8500000.00"),
    )
    jalur = JalurMasuk(nama="SNBP")
    db.add_all([prodi_ti, prodi_ek, prodi_khusus, jalur])
    db.flush()

    mhs_ti = CalonMahasiswa(
        nama_lengkap="Andi Teknik",
        email="andi@sevima.ac.id",
        phone="08111111111",
        tanggal_lahir=date(2005, 1, 10),
        program_studi_id=prodi_ti.id,
        jalur_masuk_id=jalur.id,
        status="approved",
        nim="2025001-0001",
    )
    mhs_ek = CalonMahasiswa(
        nama_lengkap="Siti Ekonomi",
        email="siti@sevima.ac.id",
        phone="08222222222",
        tanggal_lahir=date(2005, 2, 20),
        program_studi_id=prodi_ek.id,
        jalur_masuk_id=jalur.id,
        status="approved",
        nim="2025002-0002",
    )
    mhs_pending = CalonMahasiswa(
        nama_lengkap="Belum Lulus PMB",
        email="pending@sevima.ac.id",
        phone="08333333333",
        tanggal_lahir=date(2005, 3, 5),
        program_studi_id=prodi_ti.id,
        jalur_masuk_id=jalur.id,
        status="pending",
        nim=None,
    )
    db.add_all([mhs_ti, mhs_ek, mhs_pending])
    db.flush()

    mk1 = MataKuliah(kode_mk="IF101", nama="Algoritma", sks=3)
    mk2 = MataKuliah(kode_mk="IF102", nama="Struktur Data", sks=3)
    r101 = Ruangan(kode="R101", nama="Ruang R101", kapasitas=40)
    dosen = DosenJadwal(nidn="00990011", nama="Dr. Dosen Finance Test")
    db.add_all([mk1, mk2, r101, dosen])
    db.flush()

    kls1 = KelasJadwal(kode_mk="IF101", nama_kelas="A", kuota=40, semester="20251")
    kls2 = KelasJadwal(kode_mk="IF102", nama_kelas="A", kuota=40, semester="20251")
    db.add_all([kls1, kls2])
    db.flush()

    db.add(
        KRS(
            nim="2025001-0001",
            semester="20251",
            status=KRSStatus.DRAFT,
            dosen_pa_id=10,
        )
    )
    seed_payment_methods(db)
    db.commit()
    return {
        "prodi_ti_id": prodi_ti.id,
        "prodi_ek_id": prodi_ek.id,
        "prodi_khusus_id": prodi_khusus.id,
        "mhs_ti_nim": mhs_ti.nim,
        "mhs_ek_nim": mhs_ek.nim,
    }


@pytest.fixture()
def finance_api_env():
    """Fixture TestClient dengan database SQLite terisolasi & token admin/dosen."""
    finance_notification_history.clear()
    SessionFactory = _make_memory_session_factory()
    with SessionFactory() as db:
        seeded = _seed_academic_base(db)

    def override_get_db():
        db = SessionFactory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_orm_db] = override_get_db
    admin_token = create_access_token(
        {"sub": "admin.akademik@sevima.ac.id", "role": "admin_akademik"}
    )
    dosen_token = create_access_token(
        {"sub": "dosen@sevima.ac.id", "role": "dosen", "dosen_id": 1, "nidn": "00990011"}
    )
    try:
        with TestClient(app) as client:
            yield {
                "client": client,
                "session_factory": SessionFactory,
                "admin_headers": {"Authorization": f"Bearer {admin_token}"},
                "dosen_headers": {"Authorization": f"Bearer {dosen_token}"},
                **seeded,
            }
    finally:
        app.dependency_overrides.clear()
        finance_notification_history.clear()


# =====================================================================
# 1. Unit Tests Terparameterisasi (Functional Core Decimal & HMAC)
# =====================================================================


@pytest.mark.parametrize(
    "base,due,as_of,status,expected",
    [
        (Decimal("5000000.00"), date(2026, 8, 15), date(2026, 8, 10), BillingStatus.UNPAID, Decimal("0.00")),
        (Decimal("5000000.00"), date(2026, 8, 15), date(2026, 8, 15), BillingStatus.UNPAID, Decimal("0.00")),
        (Decimal("5000000.00"), date(2026, 8, 15), date(2026, 8, 16), BillingStatus.UNPAID, Decimal("100000.00")),
        (Decimal("5000000.00"), date(2026, 8, 15), date(2026, 9, 14), BillingStatus.UNPAID, Decimal("100000.00")),
        (Decimal("5000000.00"), date(2026, 8, 15), date(2026, 9, 15), BillingStatus.PARTIAL, Decimal("200000.00")),
        (Decimal("5000000.00"), date(2026, 8, 15), date(2027, 2, 15), BillingStatus.OVERDUE, Decimal("500000.00")),
        (Decimal("5000000.00"), date(2026, 8, 15), date(2026, 11, 20), BillingStatus.PAID, Decimal("0.00")),
    ],
)
def test_calculate_late_fee_cases(
    base: Decimal,
    due: date,
    as_of: date,
    status: BillingStatus,
    expected: Decimal,
) -> None:
    cfg = LateFeeConfig(
        rate_per_month=Decimal("0.02"),
        max_rate=Decimal("0.10"),
        grace_days=0,
    )
    assert calculate_late_fee(base, due, as_of, status, cfg) == expected


def test_calculate_late_fee_respects_grace_days() -> None:
    cfg = LateFeeConfig(
        rate_per_month=Decimal("0.02"),
        max_rate=Decimal("0.10"),
        grace_days=5,
    )
    assert (
        calculate_late_fee(
            Decimal("4000000.00"),
            date(2026, 8, 15),
            date(2026, 8, 20),
            BillingStatus.UNPAID,
            cfg,
        )
        == Decimal("0.00")
    )
    assert (
        calculate_late_fee(
            Decimal("4000000.00"),
            date(2026, 8, 15),
            date(2026, 8, 21),
            BillingStatus.UNPAID,
            cfg,
        )
        == Decimal("80000.00")
    )


@pytest.mark.parametrize(
    "total_due,total_paid,due,as_of,expected",
    [
        (Decimal("5000000.00"), Decimal("0.00"), date(2026, 8, 15), date(2026, 8, 10), BillingStatus.UNPAID),
        (Decimal("5000000.00"), Decimal("2000000.00"), date(2026, 8, 15), date(2026, 8, 10), BillingStatus.PARTIAL),
        (Decimal("5000000.00"), Decimal("5000000.00"), date(2026, 8, 15), date(2026, 8, 10), BillingStatus.PAID),
        (Decimal("5000000.00"), Decimal("5200000.00"), date(2026, 8, 15), date(2026, 9, 10), BillingStatus.PAID),
        (Decimal("5000000.00"), Decimal("2000000.00"), date(2026, 8, 15), date(2026, 8, 16), BillingStatus.OVERDUE),
        (Decimal("5000000.00"), Decimal("0.00"), date(2026, 8, 15), date(2026, 8, 16), BillingStatus.OVERDUE),
    ],
)
def test_determine_billing_status_cases(
    total_due: Decimal,
    total_paid: Decimal,
    due: date,
    as_of: date,
    expected: BillingStatus,
) -> None:
    assert determine_billing_status(total_due, total_paid, due, as_of) == expected


@pytest.mark.parametrize(
    "nama,fakultas,explicit,expected",
    [
        ("Teknik Informatika", "Fakultas Teknik", None, Decimal("5000000.00")),
        ("Manajemen", "Fakultas Ekonomi", None, Decimal("4000000.00")),
        ("Ilmu Hukum", "Fakultas Hukum", None, Decimal("4500000.00")),
        ("Teknik Elektro", "Fakultas Teknik", Decimal("6250000.00"), Decimal("6250000.00")),
    ],
)
def test_resolve_spp_amount_cases(
    nama: str,
    fakultas: str,
    explicit: Decimal | None,
    expected: Decimal,
) -> None:
    assert resolve_spp_amount(nama, fakultas, explicit) == expected


def test_webhook_hmac_signature_verification() -> None:
    raw = b'{"transaction_id":"TX-1","amount":"5000000.00","status":"paid","billing_id":1}'
    secret = "rahasia-kampus"
    sig = compute_webhook_signature(raw, secret)
    assert verify_webhook_signature(raw, sig, secret) is True
    assert verify_webhook_signature(raw, f"sha256={sig}", secret) is True
    assert verify_webhook_signature(raw, "0" * 64, secret) is False
    assert verify_webhook_signature(raw, None, secret) is False
    assert verify_webhook_signature(raw, sig, "") is False


# =====================================================================
# 2. Property-Based Testing (Hypothesis)
# =====================================================================


@h_settings(max_examples=200)
@given(
    total_due=st.integers(min_value=100_000, max_value=10_000_000),
    payments=st.lists(st.integers(min_value=1, max_value=3_000_000), min_size=1, max_size=12),
)
def test_properti_pembayaran_kumulatif_monotonik(
    total_due: int, payments: list[int]
) -> None:
    """Properti: status menjadi paid tepat saat akumulasi pembayaran >= total_due dan sisa tidak pernah negatif."""
    due_dec = Decimal(total_due).quantize(Decimal("0.01"))
    due_dt = date(2026, 8, 15)
    paid_sum = Decimal("0.00")

    for p in payments:
        paid_sum += Decimal(p).quantize(Decimal("0.01"))
        st_now = determine_billing_status(due_dec, paid_sum, due_dt, date(2026, 8, 10))
        remaining = max(Decimal("0.00"), due_dec - paid_sum)
        assert remaining >= Decimal("0.00")
        if paid_sum >= due_dec:
            assert st_now == BillingStatus.PAID
        else:
            assert st_now == BillingStatus.PARTIAL


@h_settings(max_examples=200)
@given(
    base=st.integers(min_value=100_000, max_value=50_000_000),
    d1=st.integers(min_value=0, max_value=300),
    d2=st.integers(min_value=0, max_value=300),
)
def test_properti_denda_monotonik_dan_terbatas(base: int, d1: int, d2: int) -> None:
    """Properti: denda keterlambatan tidak pernah negatif, monotonik terhadap hari telat, dan <= max_rate."""
    low, high = min(d1, d2), max(d1, d2)
    due_dt = date(2026, 8, 1)
    cfg = LateFeeConfig()
    base_dec = Decimal(base).quantize(Decimal("0.01"))

    fee1 = calculate_late_fee(
        base_dec, due_dt, due_dt + timedelta(days=low), BillingStatus.UNPAID, cfg
    )
    fee2 = calculate_late_fee(
        base_dec, due_dt, due_dt + timedelta(days=high), BillingStatus.UNPAID, cfg
    )
    max_allowed = (base_dec * cfg.max_rate).quantize(Decimal("0.01"))

    assert Decimal("0.00") <= fee1 <= fee2 <= max_allowed


# =====================================================================
# 3. Integrasi BillingService: Generate, Cicilan Kumulatif, Denda, & Reminder
# =====================================================================


def test_generate_billing_prodi_due_date_dan_idempoten() -> None:
    SessionFactory = _make_memory_session_factory()
    with SessionFactory() as db:
        _seed_academic_base(db)
        svc = BillingService(db=db)
        sem_start = date(2026, 8, 1)

        res1 = svc.generate_billing(semester="20261", semester_start=sem_start)
        assert res1.created_count == 2  # Hanya mahasiswa approved, pending dilewati
        assert res1.skipped_count == 0
        assert res1.due_date == date(2026, 8, 15)  # +14 hari (2 minggu)

        bill_ti = db.scalars(
            select(Billing).where(Billing.nim == "2025001-0001", Billing.semester == "20261")
        ).first()
        bill_ek = db.scalars(
            select(Billing).where(Billing.nim == "2025002-0002", Billing.semester == "20261")
        ).first()
        assert bill_ti is not None and bill_ti.amount == Decimal("5000000.00")
        assert bill_ti.status == BillingStatus.UNPAID
        assert bill_ek is not None and bill_ek.amount == Decimal("4000000.00")
        assert bill_ek.status == BillingStatus.UNPAID

        notifs = list(db.scalars(select(Notifikasi)).all())
        assert len(notifs) == 2

        # Idempoten jika dijalankan ulang
        res2 = svc.generate_billing(semester="20261", semester_start=sem_start)
        assert res2.created_count == 0
        assert res2.skipped_count == 2


def test_cicilan_kumulatif_overpayment_dan_tolak_sudah_lunas() -> None:
    SessionFactory = _make_memory_session_factory()
    history: deque[NotificationRecord] = deque(maxlen=50)
    channel = LogChannel("EMAIL", history=history)

    with SessionFactory() as db:
        _seed_academic_base(db)
        svc = BillingService(db=db, email_channel=channel)
        svc.generate_billing(semester="20251", semester_start=date(2026, 8, 1))
        billing = db.scalars(
            select(Billing).where(Billing.nim == "2025001-0001")
        ).first()
        assert billing is not None

        # Pembayaran tidak valid <= 0 -> 422
        with pytest.raises(InvalidPaymentAmountError):
            svc.process_payment(billing.id, Decimal("0.00"), "MANUAL_CASH")

        # Cicilan 1: 2jt < 5jt -> partial
        p1 = svc.process_payment(
            billing.id,
            Decimal("2000000.00"),
            "QRIS",
            transaction_id="TX-CICIL-1",
            as_of=date(2026, 8, 5),
        )
        assert p1.new_status == BillingStatus.PARTIAL
        assert p1.billing.amount_paid == Decimal("2000000.00")
        assert p1.billing.remaining == Decimal("3000000.00")

        # Cicilan 2: 3.5jt -> kumulatif 5.5jt >= 5jt -> HARUS paid (bukan partial!)
        p2 = svc.process_payment(
            billing.id,
            Decimal("3500000.00"),
            "VA_BCA",
            transaction_id="TX-CICIL-2",
            as_of=date(2026, 8, 6),
        )
        assert p2.previous_status == BillingStatus.PARTIAL
        assert p2.new_status == BillingStatus.PAID
        assert p2.billing.remaining == Decimal("0.00")
        assert p2.overpayment == Decimal("500000.00")
        assert len(history) == 2

        # Bayar lagi setelah paid -> 409 BillingAlreadyPaidError
        with pytest.raises(BillingAlreadyPaidError):
            svc.process_payment(
                billing.id,
                Decimal("100000.00"),
                "MANUAL_CASH",
                transaction_id="TX-CICIL-3",
            )


def test_overdue_denda_dan_reminder_idempoten_harian() -> None:
    SessionFactory = _make_memory_session_factory()
    history: deque[NotificationRecord] = deque(maxlen=50)
    channel = LogChannel("EMAIL", history=history)

    with SessionFactory() as db:
        _seed_academic_base(db)
        svc = BillingService(db=db, email_channel=channel)
        svc.generate_billing(semester="20251", semester_start=date(2026, 8, 1))
        # Due date = 2026-08-15; cek pada 2026-09-20 (36 hari telat -> 2 bulan -> denda 4%)
        res1 = svc.refresh_overdue_and_send_reminders(as_of=date(2026, 9, 20))
        assert res1.overdue_updated == 2
        assert res1.late_fees_applied == 2
        assert res1.reminders_sent == 2
        assert len(history) == 2

        bill_ti = db.scalars(
            select(Billing).where(Billing.nim == "2025001-0001")
        ).first()
        assert bill_ti is not None
        assert bill_ti.status == BillingStatus.OVERDUE
        assert bill_ti.late_fee == Decimal("200000.00")
        assert bill_ti.total_due == Decimal("5200000.00")

        # Jalankan ulang di hari yang sama -> tidak kirim reminder ganda
        res2 = svc.refresh_overdue_and_send_reminders(as_of=date(2026, 9, 20))
        assert res2.reminders_sent == 0
        assert len(history) == 2


# =====================================================================
# 4. Webhook Gateway & Blokir KRS Terintegrasi
# =====================================================================


def test_webhook_hmac_update_unpaid_ke_paid_idempoten_dan_non_sukses(
    finance_api_env: dict,
) -> None:
    client: TestClient = finance_api_env["client"]
    admin_headers = finance_api_env["admin_headers"]

    # Generate tagihan semester 20251 (jatuh tempo 14 hari ke depan)
    gen_resp = client.post(
        "/api/finance/billings/generate",
        json={"semester": "20251", "semester_start": date.today().isoformat()},
        headers=admin_headers,
    )
    assert gen_resp.status_code == 200
    bill_ti = next(
        b for b in gen_resp.json()["billings"] if b["nim"] == "2025001-0001"
    )
    bid = bill_ti["id"]

    # 1. Signature tidak valid / hilang -> 401
    bad_resp = client.post(
        "/api/finance/webhook",
        json={
            "billing_id": bid,
            "transaction_id": "GW-BAD-1",
            "amount": "5000000.00",
            "status": "paid",
        },
        headers={"X-Webhook-Signature": "invalid-signature"},
    )
    assert bad_resp.status_code == 401

    # 2. Webhook gagal tidak boleh mengubah saldo tagihan
    fail_payload = json.dumps(
        {
            "billing_id": bid,
            "transaction_id": "GW-FAIL-1",
            "amount": "5000000.00",
            "status": "failed",
            "payment_method": "VA_BCA",
        },
        separators=(",", ":"),
    ).encode("utf-8")
    fail_sig = compute_webhook_signature(fail_payload, settings.PAYMENT_WEBHOOK_SECRET)
    fail_resp = client.post(
        "/api/finance/webhook",
        content=fail_payload,
        headers={
            "Content-Type": "application/json",
            "X-Webhook-Signature": fail_sig,
        },
    )
    assert fail_resp.status_code == 200
    assert fail_resp.json()["processed_payment"] is False
    assert fail_resp.json()["billing_status"] == "unpaid"

    # 3. Webhook valid paid -> 200 OK, billing paid, email receipt dikirim
    ok_payload = json.dumps(
        {
            "billing_id": bid,
            "transaction_id": "GW-OK-202611-1",
            "amount": "5000000.00",
            "status": "paid",
            "payment_method": "VA_BCA",
        },
        separators=(",", ":"),
    ).encode("utf-8")
    ok_sig = compute_webhook_signature(ok_payload, settings.PAYMENT_WEBHOOK_SECRET)
    ok_resp = client.post(
        "/api/finance/webhook",
        content=ok_payload,
        headers={
            "Content-Type": "application/json",
            "X-Webhook-Signature": ok_sig,
        },
    )
    assert ok_resp.status_code == 200
    body = ok_resp.json()
    assert body["ok"] is True
    assert body["processed_payment"] is True
    assert body["billing_status"] == "paid"
    assert body["idempotent_replay"] is False

    # Cek receipt email simulasi tercatat
    receipts = client.get("/api/finance/receipts", headers=admin_headers)
    assert receipts.status_code == 200
    assert any("receipt:GW-OK-202611-1" == r["key"] for r in receipts.json())

    # 4. Replay webhook dengan transaction_id yang sama -> idempoten (tidak menggandakan saldo)
    replay_resp = client.post(
        "/api/finance/webhook",
        content=ok_payload,
        headers={
            "Content-Type": "application/json",
            "X-Webhook-Signature": ok_sig,
        },
    )
    assert replay_resp.status_code == 200
    assert replay_resp.json()["idempotent_replay"] is True


def test_blokir_krs_saat_ada_tunggakan_dan_terbuka_setelah_lunas(
    finance_api_env: dict,
) -> None:
    client: TestClient = finance_api_env["client"]
    admin_headers = finance_api_env["admin_headers"]
    nim = "2025001-0001"

    # Sebelum ada tagihan billing sama sekali -> pengisian KRS diperbolehkan
    r_free = client.post(f"/api/krs/{nim}/courses", json={"kode_mk": "IF101"})
    assert r_free.status_code == 201

    # Terbitkan tagihan SPP (status unpaid, jatuh tempo 14 hari ke depan)
    gen_resp = client.post(
        "/api/finance/billings/generate",
        json={"semester": "20251", "semester_start": date.today().isoformat()},
        headers=admin_headers,
    )
    assert gen_resp.status_code == 200
    bill_ti = next(b for b in gen_resp.json()["billings"] if b["nim"] == nim)
    bid = bill_ti["id"]

    # Mahasiswa dengan tagihan unpaid diblokir tambah MK, hapus MK, & submit KRS -> 403
    r_add_blocked = client.post(f"/api/krs/{nim}/courses", json={"kode_mk": "IF102"})
    assert r_add_blocked.status_code == 403
    assert "diblokir" in r_add_blocked.json()["detail"].lower()

    r_del_blocked = client.delete(f"/api/krs/{nim}/courses/IF101")
    assert r_del_blocked.status_code == 403

    r_sub_blocked = client.post(f"/api/krs/{nim}/submit")
    assert r_sub_blocked.status_code == 403

    # Bayar cicilan sebagian (partial) -> KRS tetap diblokir
    r_partial = client.post(
        "/api/finance/payments",
        json={
            "billing_id": bid,
            "amount": "2000000.00",
            "method_code": "QRIS",
            "transaction_id": "TX-KRS-PARTIAL",
        },
        headers=admin_headers,
    )
    assert r_partial.status_code == 201
    assert r_partial.json()["new_status"] == "partial"
    assert client.post(f"/api/krs/{nim}/courses", json={"kode_mk": "IF102"}).status_code == 403

    # Lunasi sisa tagihan lewat webhook -> blokir KRS langsung terbuka
    sign_resp = client.post(
        "/api/finance/webhook/sign",
        json={
            "billing_id": bid,
            "transaction_id": "GW-KRS-LUNAS",
            "amount": "3000000.00",
            "status": "paid",
            "payment_method": "VA_BCA",
        },
        headers=admin_headers,
    )
    assert sign_resp.status_code == 200
    signed = sign_resp.json()
    wh_resp = client.post(
        "/api/finance/webhook",
        content=signed["payload_json"],
        headers={
            "Content-Type": "application/json",
            "X-Webhook-Signature": signed["signature"],
        },
    )
    assert wh_resp.status_code == 200
    assert wh_resp.json()["billing_status"] == "paid"

    r_add_ok = client.post(f"/api/krs/{nim}/courses", json={"kode_mk": "IF102"})
    assert r_add_ok.status_code == 201
    r_sub_ok = client.post(f"/api/krs/{nim}/submit")
    assert r_sub_ok.status_code == 200
    assert r_sub_ok.json()["status"] == "SUBMITTED"


def test_tunggakan_validator_chain_dan_krs_manager_direct() -> None:
    SessionFactory = _make_memory_session_factory()
    with SessionFactory() as db:
        _seed_academic_base(db)
        svc = BillingService(db=db)
        svc.generate_billing(semester="20251", semester_start=date(2026, 8, 1))

        mk = db.get(MataKuliah, "IF101")
        assert mk is not None

        chain = build_chain([TunggakanValidator()])
        ctx = KRSContext("2025001-0001", "20251", [], mk, db=db)
        res = chain.validate(ctx)
        assert res.ok is False
        assert "diblokir" in res.message.lower()

        mgr = KRSManager(db=db, semester="20251")
        with pytest.raises(KRSBillingBlockedError):
            mgr.add_course("2025001-0001", "IF101")


# =====================================================================
# 5. APScheduler Background Jobs
# =====================================================================


def test_finance_scheduler_cron_jobs_lifecycle_dan_eksekusi() -> None:
    SessionFactory = _make_memory_session_factory()
    with SessionFactory() as db:
        _seed_academic_base(db)

    mgr = FinanceSchedulerManager(session_factory=SessionFactory)
    assert mgr.is_running is False
    jobs_before = mgr.get_jobs_status()
    job_ids = {j["id"] for j in jobs_before}
    assert job_ids == {"generate_semester_billing", "daily_overdue_and_reminder"}

    mgr.start()
    try:
        assert mgr.is_running is True
        jobs_running = mgr.get_jobs_status()
        assert all(j["next_run_time"] is not None for j in jobs_running)

        gen_res = mgr.run_generate_billing_now(
            semester="20261", semester_start=date(2026, 8, 1)
        )
        assert gen_res.created_count == 2

        rem_res = mgr.run_reminder_job_now(as_of=date(2026, 9, 20))
        assert rem_res.overdue_updated == 2
        assert rem_res.reminders_sent == 2
    finally:
        mgr.shutdown()

    assert mgr.is_running is False


# =====================================================================
# 6. AI Financial Insights (CSV + LLM Guardrail + Fallback)
# =====================================================================


def test_ai_financial_insights_csv_deterministik_top10_dan_tunggakan_2_bulan() -> None:
    lines = ["nim,jumlah,tanggal,status"]
    # 3 mahasiswa lunas bulan ini (November 2026) -> 13jt
    lines.append("2026001,5000000,2026-11-02,paid")
    lines.append("2026002,4000000,2026-11-05,paid")
    lines.append("2026003,4000000,2026-11-10,paid")
    # 12 mahasiswa menunggak dengan nominal berbeda agar menguji Top 10 & >2 bulan (as_of=2026-11-20)
    # 5 diantaranya berumur > 60 hari (August 2026)
    for i in range(1, 13):
        amt = 1_000_000 + i * 250_000
        tgl = "2026-08-15" if i <= 5 else "2026-10-25"
        st_str = "overdue" if i <= 5 else "unpaid"
        lines.append(f"20261{i:02d},{amt},{tgl},{st_str}")

    csv_text = "\n".join(lines)
    report = generate_financial_insights_from_csv(
        csv_text, as_of=date(2026, 11, 20), llm_client=FakeLLMClient("invalid-json")
    )

    assert report["ai_source"] == "deterministic_fallback"
    assert report["total_revenue_bulan_ini"] == "13000000.00"
    assert report["total_revenue_bulan_ini_formatted"] == "Rp 13.000.000"
    assert report["total_mahasiswa"] == 15
    assert report["mahasiswa_lunas"] == 3
    assert report["collection_rate_percent"] == "20.00"
    assert len(report["top_10_tunggakan"]) == 10
    assert report["top_10_tunggakan"][0]["nim"] == "2026112"
    assert report["top_10_tunggakan"][0]["total_tunggakan"] == "4000000.00"
    assert report["mahasiswa_tunggakan_lebih_2_bulan"] == 5
    assert (
        report["rekomendasi"]
        == "Kirim reminder ke 5 mahasiswa dengan tunggakan >2 bulan"
    )


def test_ai_financial_insights_guardrail_llm_tidak_ubah_angka() -> None:
    rows = [
        PaymentCSVRow("MHS1", Decimal("5000000.00"), date(2026, 11, 3), "paid"),
        PaymentCSVRow("MHS2", Decimal("4000000.00"), date(2026, 8, 1), "overdue"),
    ]
    fake = FakeLLMClient(
        json.dumps(
            {
                "ringkasan_eksekutif": "Pendapatan bulan November berjalan baik dengan satu mahasiswa overdue.",
                "saran_tindak_lanjut": ["Kirim reminder email segera kepada mahasiswa menunggak."],
            }
        )
    )
    report = generate_financial_insights(
        rows, as_of=date(2026, 11, 20), llm_client=fake
    )
    assert report["ai_source"] == "llm"
    assert report["total_revenue_bulan_ini"] == "5000000.00"
    assert report["collection_rate_percent"] == "50.00"
    assert report["mahasiswa_tunggakan_lebih_2_bulan"] == 1
    assert "MHS1" not in (fake.last_prompt or "")  # PII tidak dikirim ke prompt LLM
    assert "Pendapatan bulan November" in report["ringkasan_eksekutif"]


# =====================================================================
# 7. Dashboard Real-Time, RBAC, Seed Demo, & UI HTML
# =====================================================================


def test_dashboard_rbac_realtime_dan_ui_html(finance_api_env: dict) -> None:
    client: TestClient = finance_api_env["client"]
    admin_headers = finance_api_env["admin_headers"]
    dosen_headers = finance_api_env["dosen_headers"]

    # RBAC: tanpa token -> 401, token dosen -> 403
    assert client.get("/api/finance/dashboard").status_code == 401
    assert client.get("/api/finance/dashboard", headers=dosen_headers).status_code == 403

    # UI HTML Dashboard Keuangan
    ui_resp = client.get("/dashboard/finance")
    assert ui_resp.status_code == 200
    assert "Dashboard Keuangan (SPP)" in ui_resp.text

    # Seed demo & cek dashboard real-time
    seed_resp = client.post("/api/finance/seed-demo?semester=20251", headers=admin_headers)
    assert seed_resp.status_code == 200

    dash_resp = client.get("/api/finance/dashboard?semester=20251", headers=admin_headers)
    assert dash_resp.status_code == 200
    dash = dash_resp.json()
    assert dash["total_mahasiswa"] >= 5
    assert dash["mahasiswa_lunas"] >= 1
    assert len(dash["per_prodi"]) >= 2
    assert len(dash["monthly_payments"]) >= 1

    # AI report langsung dari DB
    ai_resp = client.get("/api/finance/ai-report?semester=20251", headers=admin_headers)
    assert ai_resp.status_code == 200
    ai_data = ai_resp.json()
    assert ai_data["mahasiswa_tunggakan_lebih_2_bulan"] >= 1
    assert "Kirim reminder ke" in ai_data["rekomendasi"]

    # Ringkasan per mahasiswa & status blokir KRS
    stu_summary = client.get("/api/finance/students/2025001-0105/summary")
    assert stu_summary.status_code == 200
    assert stu_summary.json()["krs_blocked"] is True
    assert stu_summary.json()["status"] == "overdue"

    # Scheduler status endpoint
    sched_resp = client.get("/api/finance/scheduler/jobs", headers=admin_headers)
    assert sched_resp.status_code == 200
    assert len(sched_resp.json()["jobs"]) == 2

    # Payment methods endpoint
    pm_resp = client.get("/api/finance/payment-methods")
    assert pm_resp.status_code == 200
    assert any(m["code"] == "VA_BCA" for m in pm_resp.json())
