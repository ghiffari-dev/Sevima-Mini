from contextlib import asynccontextmanager
from pathlib import Path
import sqlite3
import sys
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from app.core.config import settings
from app.models.attendance import AttendanceError
from app.models.finance import FinanceError
from app.models.grade import GradeError
from app.models.krs import KRSError
from app.models.schedule import ScheduleError
from app.services.finance_scheduler import default_finance_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Mengelola siklus hidup background scheduler modul keuangan saat aplikasi aktif."""
    if settings.FINANCE_SCHEDULER_ENABLED and "pytest" not in sys.modules:
        default_finance_scheduler.start()
    try:
        yield
    finally:
        default_finance_scheduler.shutdown()


app = FastAPI(title="PMB Academic System API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(KRSError)
async def krs_error(request: Request, exc: KRSError):
    return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})


@app.exception_handler(ScheduleError)
async def schedule_error(request: Request, exc: ScheduleError):
    return JSONResponse(status_code=exc.status_code, content=exc.body())


@app.exception_handler(GradeError)
async def grade_error(request: Request, exc: GradeError):
    return JSONResponse(status_code=exc.status_code, content=exc.body())


@app.exception_handler(FinanceError)
async def finance_error(request: Request, exc: FinanceError):
    return JSONResponse(status_code=exc.status_code, content=exc.body())


@app.exception_handler(AttendanceError)
async def attendance_error(request: Request, exc: AttendanceError):
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.body(),
        headers=exc.headers or None,
    )



DB_PATH = "backend/pmb.db"

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

from app.routers import attendance, auth, finance, grade, krs, pmb, schedule
app.include_router(auth.router, prefix="/api/auth", tags=["Auth"])
app.include_router(pmb.router, prefix="/api/pmb", tags=["PMB"])
app.include_router(krs.router, prefix="/api/krs", tags=["KRS"])
app.include_router(schedule.router, prefix="/api/schedules", tags=["Schedules"])
app.include_router(grade.router, prefix="/api", tags=["Grades"])
app.include_router(finance.router, prefix="/api/finance", tags=["Finance"])
app.include_router(attendance.router, prefix="/api/attendance", tags=["Attendance"])
app.include_router(
    attendance.router,
    prefix="/attendance",
    tags=["Attendance"],
    include_in_schema=False,
)


_CONFLICT_UI_PATH = Path(__file__).resolve().parent / "static" / "conflict_resolver.html"
_GRADE_UI_PATH = Path(__file__).resolve().parent / "static" / "grade_input.html"
_FINANCE_UI_PATH = Path(__file__).resolve().parent / "static" / "finance_dashboard.html"
_ATTENDANCE_UI_PATH = Path(__file__).resolve().parent / "static" / "attendance_dashboard.html"


@app.get("/dashboard/conflicts", include_in_schema=False)
def conflict_resolver_dashboard():
    """Menyajikan dashboard web Conflict Resolver UI untuk admin akademik."""
    return FileResponse(_CONFLICT_UI_PATH)


@app.get("/dashboard/grades", include_in_schema=False)
def grade_input_dashboard():
    """Menyajikan form web input nilai & audit trail untuk dosen pengampu."""
    return FileResponse(_GRADE_UI_PATH)


@app.get("/dashboard/finance", include_in_schema=False)
def finance_dashboard():
    """Menyajikan Dashboard Keuangan SPP (real-time tagihan, collection rate, webhook, & AI insights)."""
    return FileResponse(_FINANCE_UI_PATH)


@app.get("/dashboard/attendance", include_in_schema=False)
def attendance_dashboard():
    """Menyajikan Dashboard Presensi QR Code Berotasi, Scanner Geolokasi, Laporan Excel, & AI Insights."""
    return FileResponse(_ATTENDANCE_UI_PATH)

