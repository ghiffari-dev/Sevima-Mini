from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
import enum
import logging
from typing import Any, Protocol, runtime_checkable
import uuid

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

notification_logger = logging.getLogger("schedule.notifications")


class EventType(str, enum.Enum):
    """Jenis event perubahan jadwal untuk Observer Pattern & Transactional Outbox."""

    SCHEDULE_CHANGED = "SCHEDULE_CHANGED"
    SCHEDULE_DELETED = "SCHEDULE_DELETED"


class NotificationMedium(str, enum.Enum):
    """Medium pengiriman notifikasi (disimulasikan lewat log)."""

    EMAIL = "EMAIL"
    SMS = "SMS"
    PUSH = "PUSH"


@dataclass(frozen=True)
class ScheduleEvent:
    """Payload event jadwal immutable (frozen) yang dikirim ke seluruh Observer."""

    event_type: EventType
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def schedule_data(self) -> dict[str, Any]:
        """Tampilan gabungan kompatibel untuk pembacaan ringkas event."""
        merged: dict[str, Any] = {}
        if self.before:
            merged.update(self.before)
            merged["old_schedule"] = self.before
        if self.after:
            merged.update(self.after)
            merged["new_schedule"] = self.after
        if self.meta:
            merged.update(self.meta)
        return merged


@dataclass(frozen=True)
class NotificationRecord:
    """Catatan hasil pengiriman notifikasi oleh satu kanal."""

    observer: str
    recipient: str
    medium: str
    event_type: str
    message: str
    timestamp: datetime
    key: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "observer": self.observer,
            "recipient": self.recipient,
            "medium": self.medium,
            "event_type": self.event_type,
            "message": self.message,
            "timestamp": self.timestamp.isoformat(),
            "key": self.key,
        }


@runtime_checkable
class NotificationChannel(Protocol):
    """Kontrak kanal pengiriman notifikasi (Strategy-like) dengan kunci idempotensi."""

    name: str

    def send(
        self,
        recipient: str,
        message: str,
        *,
        key: str,
        observer: str = "",
        event_type: str = "",
    ) -> NotificationRecord | None:
        ...


class LogChannel:
    """Kanal simulasi notifikasi ke logger beserta deduplikasi berbasis kunci idempotensi."""

    def __init__(
        self,
        name: str,
        sent_keys: set[str] | None = None,
        history: deque[NotificationRecord] | None = None,
    ) -> None:
        self.name = name.strip().upper()
        self._sent_keys: set[str] = sent_keys if sent_keys is not None else set()
        self._history = history

    @property
    def sent_keys(self) -> set[str]:
        return set(self._sent_keys)

    def clear_sent_keys(self) -> None:
        self._sent_keys.clear()

    def send(
        self,
        recipient: str,
        message: str,
        *,
        key: str,
        observer: str = "",
        event_type: str = "",
    ) -> NotificationRecord | None:
        """Mengirim notifikasi ke log maksimal satu kali per idempotency key."""
        if key in self._sent_keys:
            return None
        self._sent_keys.add(key)

        notification_logger.info(
            "[SIMULATED %s] key=%s observer=%s recipient=%s event=%s msg=%s",
            self.name,
            key,
            observer,
            recipient,
            event_type,
            message,
        )
        rec = NotificationRecord(
            observer=observer,
            recipient=recipient,
            medium=self.name,
            event_type=event_type,
            message=message,
            timestamp=datetime.now(timezone.utc),
            key=key,
        )
        if self._history is not None:
            self._history.append(rec)
        return rec


@runtime_checkable
class ParticipantRepository(Protocol):
    """Kontrak repository peserta kelas untuk StudentObserver."""

    def get_nims_by_class(self, kelas_id: int) -> list[str]:
        ...


class SQLAlchemyParticipantRepository:
    """Implementasi ParticipantRepository berbasis SQLAlchemy 2.0 pada tabel KRS & KRSDetail."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def get_nims_by_class(self, kelas_id: int) -> list[str]:
        from app.models.krs import KRS, KRSDetail
        from app.models.schedule import Kelas

        kelas = self.db.get(Kelas, kelas_id)
        if kelas is None:
            return []
        stmt = (
            select(KRS.nim)
            .join(KRSDetail, KRSDetail.krs_id == KRS.id)
            .where(
                KRS.semester == kelas.semester,
                or_(
                    KRSDetail.kelas_id == kelas.id,
                    (KRSDetail.kelas_id.is_(None))
                    & (KRSDetail.kode_mk == kelas.kode_mk),
                ),
            )
            .distinct()
            .order_by(KRS.nim.asc())
        )
        return [str(nim) for nim in self.db.scalars(stmt).all()]


@runtime_checkable
class ScheduleObserver(Protocol):
    """Kontrak Observer menggunakan typing.Protocol (structural typing tanpa pewarisan wajib)."""

    def update(self, event: ScheduleEvent) -> list[NotificationRecord] | None:
        ...


def _slot_label(info: dict[str, Any] | None) -> str:
    if not info:
        return "-"
    hari = info.get("hari_nama") or info.get("hari") or "-"
    jam = info.get("jam") or (
        f"{info.get('jam_mulai', '?')}-{info.get('jam_selesai', '?')}"
        if info.get("jam_mulai")
        else "-"
    )
    ruangan = info.get("ruangan_kode") or info.get("ruangan") or "-"
    return f"{hari} {jam} ({ruangan})"


def _describe_event(event: ScheduleEvent) -> str:
    """Membentuk ringkasan before -> after yang informatif untuk seluruh Observer."""
    ref = event.after or event.before or {}
    kode_mk = ref.get("kode_mk") or (event.before or {}).get("kode_mk") or "-"
    nama_mk = (
        ref.get("nama_mk")
        or ref.get("mata_kuliah")
        or (event.before or {}).get("nama_mk")
        or kode_mk
    )
    if (
        event.event_type == EventType.SCHEDULE_CHANGED
        and event.before is not None
        and event.after is not None
    ):
        return (
            f"{nama_mk} ({kode_mk}) dipindah dari "
            f"{_slot_label(event.before)} ke {_slot_label(event.after)}"
        )
    if event.event_type == EventType.SCHEDULE_DELETED:
        return f"{nama_mk} ({kode_mk}) pada {_slot_label(event.before)} dihapus"
    return f"{nama_mk} ({kode_mk}) -> {_slot_label(ref)}"


class StudentObserver:
    """Observer Mahasiswa: mencari peserta via ParticipantRepository dan kirim lewat Email & Push."""

    def __init__(
        self,
        participant_repo: ParticipantRepository | None = None,
        channels: list[NotificationChannel] | None = None,
    ) -> None:
        self.participant_repo = participant_repo
        self.channels: list[NotificationChannel] = (
            list(channels)
            if channels is not None
            else [
                LogChannel(NotificationMedium.EMAIL.value),
                LogChannel(NotificationMedium.PUSH.value),
            ]
        )

    def _resolve_nims(self, event: ScheduleEvent) -> list[str]:
        ref = event.after or event.before or {}
        kelas_id = ref.get("kelas_id")
        if self.participant_repo is not None and kelas_id is not None:
            found = self.participant_repo.get_nims_by_class(int(kelas_id))
            if found:
                return found
        meta_nims = list(event.meta.get("affected_nims") or [])
        return [str(n) for n in meta_nims] if meta_nims else ["mahasiswa-terdampak"]

    def update(self, event: ScheduleEvent) -> list[NotificationRecord]:
        recipients = self._resolve_nims(event)
        summary = _describe_event(event)
        records: list[NotificationRecord] = []

        for nim in recipients:
            msg = (
                f"[{event.event_type.value}] Perubahan jadwal kuliah: {summary}. "
                "Silakan cek kembali KRS Anda."
            )
            for channel in self.channels:
                recipient = (
                    f"{nim}@student.sevima.ac.id"
                    if channel.name == NotificationMedium.EMAIL.value
                    and "@" not in str(nim)
                    else str(nim)
                )
                key = f"{event.event_id}:{nim}:{channel.name}"
                rec = channel.send(
                    recipient,
                    msg,
                    key=key,
                    observer="StudentObserver",
                    event_type=event.event_type.value,
                )
                if rec is not None:
                    records.append(rec)
        return records


class LecturerObserver:
    """Observer Dosen pengampu (termasuk dosen lama jika diganti) lewat Email & SMS."""

    def __init__(self, channels: list[NotificationChannel] | None = None) -> None:
        self.channels: list[NotificationChannel] = (
            list(channels)
            if channels is not None
            else [
                LogChannel(NotificationMedium.EMAIL.value),
                LogChannel(NotificationMedium.SMS.value),
            ]
        )

    def update(self, event: ScheduleEvent) -> list[NotificationRecord]:
        lecturers: list[str] = []
        candidates = (
            (event.after or {}).get("dosen"),
            (event.before or {}).get("dosen"),
            event.meta.get("dosen"),
            event.meta.get("old_dosen"),
        )
        for candidate in candidates:
            if candidate and str(candidate).strip() and str(candidate) not in lecturers:
                lecturers.append(str(candidate))
        if not lecturers:
            lecturers = ["Dosen Pengampu"]

        summary = _describe_event(event)
        records: list[NotificationRecord] = []
        for dosen_name in lecturers:
            msg = (
                f"[{event.event_type.value}] Pemberitahuan jadwal mengajar untuk "
                f"{dosen_name}: {summary}."
            )
            for channel in self.channels:
                key = f"{event.event_id}:dosen:{dosen_name}:{channel.name}"
                rec = channel.send(
                    dosen_name,
                    msg,
                    key=key,
                    observer="LecturerObserver",
                    event_type=event.event_type.value,
                )
                if rec is not None:
                    records.append(rec)
        return records


class AdminObserver:
    """Observer Admin Akademik untuk audit perubahan jadwal lewat Email, SMS, & Push."""

    def __init__(
        self,
        admin_contact: str = "admin.akademik@sevima.ac.id",
        channels: list[NotificationChannel] | None = None,
    ) -> None:
        self.admin_contact = admin_contact
        self.channels: list[NotificationChannel] = (
            list(channels)
            if channels is not None
            else [
                LogChannel(NotificationMedium.EMAIL.value),
                LogChannel(NotificationMedium.SMS.value),
                LogChannel(NotificationMedium.PUSH.value),
            ]
        )

    def update(self, event: ScheduleEvent) -> list[NotificationRecord]:
        summary = _describe_event(event)
        invalidated_count = len(event.meta.get("invalidated_krs_ids") or [])
        conflicts_count = len(event.meta.get("conflicts") or [])
        msg = (
            f"[{event.event_type.value}] Audit perubahan jadwal: {summary} "
            f"(KRS direvisi: {invalidated_count}, bentrok terdeteksi: {conflicts_count})."
        )
        records: list[NotificationRecord] = []
        for channel in self.channels:
            key = f"{event.event_id}:{self.admin_contact}:{channel.name}"
            rec = channel.send(
                self.admin_contact,
                msg,
                key=key,
                observer="AdminObserver",
                event_type=event.event_type.value,
            )
            if rec is not None:
                records.append(rec)
        return records


AcademicAdminObserver = AdminObserver


@dataclass
class NotifyReport:
    """Ringkasan hasil pemanggilan notify(): rekaman terkirim & daftar observer gagal."""

    event_id: str
    records: list[NotificationRecord] = field(default_factory=list)
    failed_observers: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return len(self.failed_observers) == 0


class ScheduleSubject:
    """Subject pada Observer Pattern dengan isolasi try/except per Observer."""

    def __init__(self, max_history: int = 500) -> None:
        self._observers: list[ScheduleObserver] = []
        self.history: deque[NotificationRecord] = deque(maxlen=max_history)

    @property
    def observers(self) -> list[ScheduleObserver]:
        return list(self._observers)

    def attach(self, observer: ScheduleObserver) -> None:
        """Mendaftarkan observer jika belum terpasang (mencegah notifikasi ganda)."""
        if observer not in self._observers:
            self._observers.append(observer)

    def detach(self, observer: ScheduleObserver) -> None:
        """Melepas observer yang sudah terdaftar."""
        self._observers = [obs for obs in self._observers if obs != observer]

    @staticmethod
    def _coerce_event(
        event_or_type: ScheduleEvent | EventType | str,
        schedule_data: dict[str, Any] | None = None,
    ) -> ScheduleEvent:
        if isinstance(event_or_type, ScheduleEvent):
            return event_or_type
        ev_type = (
            event_or_type
            if isinstance(event_or_type, EventType)
            else EventType(str(event_or_type))
        )
        data = dict(schedule_data or {})
        before = data.get("old_schedule") if isinstance(data.get("old_schedule"), dict) else None
        after = data.get("new_schedule") if isinstance(data.get("new_schedule"), dict) else None
        if before is None and after is None:
            if ev_type == EventType.SCHEDULE_DELETED:
                before = data
            else:
                after = data
        meta = {
            k: v
            for k, v in data.items()
            if k not in {"old_schedule", "new_schedule"}
        }
        return ScheduleEvent(event_type=ev_type, before=before, after=after, meta=meta)

    def notify(
        self,
        event_or_type: ScheduleEvent | EventType | str,
        schedule_data: dict[str, Any] | None = None,
    ) -> NotifyReport:
        """Menyiarkan ScheduleEvent ke salinan daftar observer; satu gagal tidak menghentikan yang lain."""
        event = self._coerce_event(event_or_type, schedule_data)
        emitted: list[NotificationRecord] = []
        failed_observers: list[str] = []

        for observer in list(self._observers):
            try:
                records = observer.update(event)
                if records:
                    for rec in records:
                        if rec not in self.history:
                            self.history.append(rec)
                        emitted.append(rec)
            except Exception as exc:
                obs_name = type(observer).__name__
                failed_observers.append(obs_name)
                notification_logger.exception(
                    "Observer %s gagal memproses event %s: %s",
                    obs_name,
                    event.event_id,
                    exc,
                )

        return NotifyReport(
            event_id=event.event_id,
            records=emitted,
            failed_observers=failed_observers,
        )


class NotificationManager(ScheduleSubject):
    """Singleton-style Manager dirangkai sekali saat startup dengan 3 Observer & 3 LogChannel."""

    def __init__(
        self,
        auto_attach_defaults: bool = True,
        max_history: int = 500,
    ) -> None:
        super().__init__(max_history=max_history)
        self._channels: list[LogChannel] = []
        if auto_attach_defaults:
            email_ch = LogChannel(NotificationMedium.EMAIL.value, history=self.history)
            sms_ch = LogChannel(NotificationMedium.SMS.value, history=self.history)
            push_ch = LogChannel(NotificationMedium.PUSH.value, history=self.history)
            self._channels = [email_ch, sms_ch, push_ch]
            self.attach(StudentObserver(channels=[email_ch, push_ch]))
            self.attach(LecturerObserver(channels=[email_ch, sms_ch]))
            self.attach(AdminObserver(channels=[email_ch, sms_ch, push_ch]))

    def get_logs(self, limit: int = 100) -> list[dict[str, Any]]:
        """Mengembalikan riwayat notifikasi terbaru dalam bentuk dictionary."""
        items = list(self.history)[-limit:]
        items.reverse()
        return [rec.to_dict() for rec in items]

    def clear_logs(self) -> None:
        """Mengosongkan riwayat log & kunci idempotensi di memori."""
        self.history.clear()
        for ch in self._channels:
            ch.clear_sent_keys()


@dataclass
class DispatchSummary:
    """Ringkasan eksekusi satu batch oleh OutboxDispatcher."""

    picked: int = 0
    sent: int = 0
    retried: int = 0
    failed: int = 0
    records: list[NotificationRecord] = field(default_factory=list)
    failed_observers: list[str] = field(default_factory=list)


class OutboxDispatcher:
    """Memproses baris outbox PENDING setelah komit memakai FOR UPDATE SKIP LOCKED & retry max 5x."""

    def __init__(
        self,
        db: Session,
        subject: ScheduleSubject,
        max_attempts: int = 5,
    ) -> None:
        self.db = db
        self.subject = subject
        self.max_attempts = max_attempts

    def run(self, limit: int = 50) -> DispatchSummary:
        from app.models.schedule import Outbox, OutboxStatus

        summary = DispatchSummary()
        try:
            stmt = (
                select(Outbox)
                .where(Outbox.status == OutboxStatus.PENDING.value)
                .order_by(Outbox.id.asc())
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
            rows = list(self.db.scalars(stmt).all())
            for row in rows:
                summary.picked += 1
                event = row.to_event()
                row.attempts = int(row.attempts or 0) + 1
                report = self.subject.notify(event)
                summary.records.extend(report.records)

                if report.ok:
                    row.status = OutboxStatus.SENT.value
                    row.last_error = None
                    row.processed_at = datetime.now(timezone.utc)
                    summary.sent += 1
                else:
                    summary.failed_observers.extend(report.failed_observers)
                    row.last_error = (
                        f"Observer gagal: {', '.join(report.failed_observers)}"
                    )[:500]
                    if row.attempts >= self.max_attempts:
                        row.status = OutboxStatus.FAILED.value
                        row.processed_at = datetime.now(timezone.utc)
                        summary.failed += 1
                    else:
                        row.status = OutboxStatus.PENDING.value
                        summary.retried += 1

            self.db.commit()
        except Exception as exc:
            notification_logger.exception("OutboxDispatcher gagal memproses batch: %s", exc)
            self.db.rollback()
        return summary


default_notification_manager = NotificationManager()
