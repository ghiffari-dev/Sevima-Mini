from __future__ import annotations

from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
import enum
import logging
from typing import Any

notification_logger = logging.getLogger("schedule.notifications")


class NotificationMedium(str, enum.Enum):
    """Medium pengiriman notifikasi (disimulasikan lewat log)."""

    EMAIL = "EMAIL"
    SMS = "SMS"
    PUSH = "PUSH"


@dataclass(frozen=True)
class ScheduleEvent:
    """Payload event perubahan jadwal yang dikirim oleh ScheduleSubject ke Observer."""

    event_type: str
    schedule_data: dict[str, Any]
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True)
class NotificationRecord:
    """Catatan hasil pengiriman notifikasi oleh satu Observer."""

    observer: str
    recipient: str
    medium: str
    event_type: str
    message: str
    timestamp: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "observer": self.observer,
            "recipient": self.recipient,
            "medium": self.medium,
            "event_type": self.event_type,
            "message": self.message,
            "timestamp": self.timestamp.isoformat(),
        }


def _describe_schedule(data: dict[str, Any]) -> str:
    """Membentuk ringkasan human-readable untuk pesan notifikasi jadwal."""
    new_info = data.get("new_schedule") if isinstance(data.get("new_schedule"), dict) else data
    kode_mk = new_info.get("kode_mk") or data.get("kode_mk") or "-"
    nama_mk = (
        new_info.get("nama_mk")
        or data.get("nama_mk")
        or data.get("mata_kuliah")
        or kode_mk
    )
    hari = new_info.get("hari_nama") or new_info.get("hari") or data.get("hari") or "-"
    jam = new_info.get("jam") or (
        f"{new_info.get('jam_mulai', '?')}-{new_info.get('jam_selesai', '?')}"
        if new_info.get("jam_mulai")
        else data.get("jam") or "-"
    )
    ruangan = new_info.get("ruangan") or data.get("ruangan") or "-"
    return f"{nama_mk} ({kode_mk}) -> {hari} {jam} di {ruangan}"


class ScheduleObserver(ABC):
    """Interface abstrak Observer untuk menerima notifikasi event jadwal."""

    @abstractmethod
    def update(self, event: ScheduleEvent) -> list[NotificationRecord]:
        """Bereaksi terhadap ScheduleEvent dan mengembalikan catatan notifikasi terkirim."""
        ...


class StudentObserver(ScheduleObserver):
    """Observer untuk Mahasiswa terdampak (simulasi Email & Push Notification)."""

    def update(self, event: ScheduleEvent) -> list[NotificationRecord]:
        data = event.schedule_data
        nims = list(data.get("affected_nims") or [])
        recipients = nims if nims else ["mahasiswa-terdampak"]
        summary = _describe_schedule(data)
        records: list[NotificationRecord] = []

        for nim in recipients:
            email_addr = f"{nim}@student.sevima.ac.id" if "@" not in str(nim) else str(nim)
            msg = f"[{event.event_type}] Perubahan jadwal kuliah: {summary}. Silakan cek kembali KRS Anda."
            for medium in (NotificationMedium.EMAIL, NotificationMedium.PUSH):
                notification_logger.info(
                    "[SIMULATED %s] observer=StudentObserver recipient=%s event=%s msg=%s",
                    medium.value,
                    email_addr if medium == NotificationMedium.EMAIL else nim,
                    event.event_type,
                    msg,
                )
                records.append(
                    NotificationRecord(
                        observer="StudentObserver",
                        recipient=email_addr if medium == NotificationMedium.EMAIL else str(nim),
                        medium=medium.value,
                        event_type=event.event_type,
                        message=msg,
                        timestamp=event.timestamp,
                    )
                )
        return records


class LecturerObserver(ScheduleObserver):
    """Observer untuk Dosen pengampu (simulasi Email & SMS)."""

    def update(self, event: ScheduleEvent) -> list[NotificationRecord]:
        data = event.schedule_data
        new_info = data.get("new_schedule") if isinstance(data.get("new_schedule"), dict) else data
        lecturers: list[str] = []
        for candidate in (new_info.get("dosen"), data.get("dosen"), data.get("old_dosen")):
            if candidate and str(candidate).strip() and str(candidate) not in lecturers:
                lecturers.append(str(candidate))
        if not lecturers:
            lecturers = ["Dosen Pengampu"]

        summary = _describe_schedule(data)
        records: list[NotificationRecord] = []
        for dosen_name in lecturers:
            msg = f"[{event.event_type}] Pemberitahuan jadwal mengajar untuk {dosen_name}: {summary}."
            for medium in (NotificationMedium.EMAIL, NotificationMedium.SMS):
                notification_logger.info(
                    "[SIMULATED %s] observer=LecturerObserver recipient=%s event=%s msg=%s",
                    medium.value,
                    dosen_name,
                    event.event_type,
                    msg,
                )
                records.append(
                    NotificationRecord(
                        observer="LecturerObserver",
                        recipient=dosen_name,
                        medium=medium.value,
                        event_type=event.event_type,
                        message=msg,
                        timestamp=event.timestamp,
                    )
                )
        return records


class AdminObserver(ScheduleObserver):
    """Observer untuk Admin Akademik (simulasi Email, SMS, & Push untuk audit/monitoring)."""

    def __init__(self, admin_contact: str = "admin.akademik@sevima.ac.id") -> None:
        self.admin_contact = admin_contact

    def update(self, event: ScheduleEvent) -> list[NotificationRecord]:
        data = event.schedule_data
        summary = _describe_schedule(data)
        invalidated_count = len(data.get("invalidated_krs_ids") or [])
        conflicts_count = len(data.get("conflicts") or [])
        msg = (
            f"[{event.event_type}] Audit perubahan jadwal: {summary} "
            f"(KRS direvisi: {invalidated_count}, bentrok terdeteksi: {conflicts_count})."
        )
        records: list[NotificationRecord] = []
        for medium in (
            NotificationMedium.EMAIL,
            NotificationMedium.SMS,
            NotificationMedium.PUSH,
        ):
            notification_logger.info(
                "[SIMULATED %s] observer=AdminObserver recipient=%s event=%s msg=%s",
                medium.value,
                self.admin_contact,
                event.event_type,
                msg,
            )
            records.append(
                NotificationRecord(
                    observer="AdminObserver",
                    recipient=self.admin_contact,
                    medium=medium.value,
                    event_type=event.event_type,
                    message=msg,
                    timestamp=event.timestamp,
                )
            )
        return records


AcademicAdminObserver = AdminObserver


class ScheduleSubject:
    """Publisher pada Observer Pattern untuk menyiarkan event perubahan jadwal."""

    def __init__(self, max_history: int = 500) -> None:
        self._observers: list[ScheduleObserver] = []
        self.history: deque[NotificationRecord] = deque(maxlen=max_history)

    @property
    def observers(self) -> list[ScheduleObserver]:
        return list(self._observers)

    def attach(self, observer: ScheduleObserver) -> None:
        """Mendaftarkan observer jika belum terpasang."""
        if observer not in self._observers:
            self._observers.append(observer)

    def detach(self, observer: ScheduleObserver) -> None:
        """Melepas observer yang sudah terdaftar."""
        self._observers = [obs for obs in self._observers if obs != observer]

    def notify(
        self, event_type: str, schedule_data: dict[str, Any]
    ) -> list[NotificationRecord]:
        """Menyiarkan event ke seluruh observer dan menyimpan log simulasinya."""
        event = ScheduleEvent(event_type=event_type, schedule_data=dict(schedule_data))
        emitted: list[NotificationRecord] = []
        for observer in list(self._observers):
            records = observer.update(event)
            for rec in records:
                self.history.append(rec)
                emitted.append(rec)
        return emitted


class NotificationManager(ScheduleSubject):
    """Manager notifikasi terpusat dengan subscriber default Mahasiswa, Dosen, & Admin."""

    def __init__(
        self, auto_attach_defaults: bool = True, max_history: int = 500
    ) -> None:
        super().__init__(max_history=max_history)
        if auto_attach_defaults:
            self.attach(StudentObserver())
            self.attach(LecturerObserver())
            self.attach(AdminObserver())

    def get_logs(self, limit: int = 100) -> list[dict[str, Any]]:
        """Mengembalikan riwayat notifikasi terbaru dalam bentuk dictionary."""
        items = list(self.history)[-limit:]
        items.reverse()
        return [rec.to_dict() for rec in items]

    def clear_logs(self) -> None:
        """Mengosongkan riwayat log notifikasi di memori."""
        self.history.clear()


default_notification_manager = NotificationManager()
