from __future__ import annotations

from datetime import date
import logging
from typing import Any, Callable

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.services.billing_service import (
    BillingService,
    GenerateBillingResult,
    ReminderJobResult,
)

logger = logging.getLogger("finance.scheduler")


def resolve_semester_code(ref_date: date | None = None) -> str:
    """Menentukan kode semester akademik (YYYY1 Ganjil / YYYY2 Genap) dari tanggal."""
    d = ref_date or date.today()
    if 2 <= d.month <= 7:
        return f"{d.year - 1}2"
    if d.month == 1:
        return f"{d.year - 1}1"
    return f"{d.year}1"


class FinanceSchedulerManager:
    """Pengelola cron job APScheduler untuk generate tagihan semester & reminder SPP harian."""

    def __init__(
        self,
        session_factory: Callable[[], Session] = SessionLocal,
        timezone_name: str = "Asia/Jakarta",
    ) -> None:
        self.session_factory = session_factory
        self.timezone_name = timezone_name
        self._scheduler: BackgroundScheduler = self._create_scheduler()

    def _create_scheduler(self) -> BackgroundScheduler:
        scheduler = BackgroundScheduler(timezone=self.timezone_name)
        scheduler.add_job(
            self.run_generate_billing_now,
            trigger=CronTrigger(
                month="2,8",
                day=1,
                hour=0,
                minute=5,
                timezone=self.timezone_name,
            ),
            id="generate_semester_billing",
            name="Generate Tagihan SPP Awal Semester",
            replace_existing=True,
        )
        scheduler.add_job(
            self.run_reminder_job_now,
            trigger=CronTrigger(
                hour=7,
                minute=0,
                timezone=self.timezone_name,
            ),
            id="daily_overdue_and_reminder",
            name="Cek Overdue & Reminder Pembayaran SPP",
            replace_existing=True,
        )
        return scheduler

    @property
    def is_running(self) -> bool:
        return bool(self._scheduler.running)

    def start(self) -> None:
        """Memulai APScheduler background scheduler secara idempoten."""
        if not self._scheduler.running:
            self._scheduler.start()
            logger.info("Finance APScheduler started with %d jobs", len(self._scheduler.get_jobs()))

    def shutdown(self) -> None:
        """Menghentikan scheduler dan menyiapkan instance bersih bila di-start ulang."""
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            self._scheduler = self._create_scheduler()
            logger.info("Finance APScheduler stopped")

    def get_jobs_status(self) -> list[dict[str, Any]]:
        """Mengembalikan daftar job terjadwal beserta trigger dan waktu eksekusi berikutnya."""
        jobs = self._scheduler.get_jobs()
        results: list[dict[str, Any]] = []
        for job in jobs:
            next_run = getattr(job, "next_run_time", None)
            results.append(
                {
                    "id": job.id,
                    "name": job.name,
                    "trigger": str(job.trigger),
                    "next_run_time": next_run.isoformat() if next_run else None,
                }
            )
        return results

    def run_generate_billing_now(
        self,
        semester: str | None = None,
        semester_start: date | None = None,
    ) -> GenerateBillingResult:
        """Menjalankan job generator tagihan SPP per semester dalam sesi DB terisolasi."""
        start_dt = semester_start or date.today()
        sem = semester or resolve_semester_code(start_dt)
        db = self.session_factory()
        try:
            service = BillingService(db=db)
            result = service.generate_billing(
                semester=sem, semester_start=start_dt
            )
            logger.info(
                "Cron generate_semester_billing finished: semester=%s created=%d skipped=%d",
                result.semester,
                result.created_count,
                result.skipped_count,
            )
            return result
        finally:
            db.close()

    def run_reminder_job_now(
        self,
        as_of: date | None = None,
        reminder_before_days: int = 3,
    ) -> ReminderJobResult:
        """Menjalankan job pengecekan overdue, denda, dan reminder SPP dalam sesi DB terisolasi."""
        db = self.session_factory()
        try:
            service = BillingService(db=db)
            result = service.refresh_overdue_and_send_reminders(
                as_of=as_of,
                reminder_before_days=reminder_before_days,
            )
            logger.info(
                "Cron daily_overdue_and_reminder finished: overdue=%d late_fees=%d reminders=%d",
                result.overdue_updated,
                result.late_fees_applied,
                result.reminders_sent,
            )
            return result
        finally:
            db.close()


default_finance_scheduler = FinanceSchedulerManager()
