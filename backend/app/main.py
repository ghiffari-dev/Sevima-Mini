from pathlib import Path
import sqlite3
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from app.models.grade import GradeError
from app.models.krs import KRSError
from app.models.schedule import ScheduleError

app = FastAPI(title="PMB Academic System API", version="1.0.0")

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


DB_PATH = "backend/pmb.db"

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

from app.routers import auth, grade, krs, pmb, schedule
app.include_router(auth.router, prefix="/api/auth", tags=["Auth"])
app.include_router(pmb.router, prefix="/api/pmb", tags=["PMB"])
app.include_router(krs.router, prefix="/api/krs", tags=["KRS"])
app.include_router(schedule.router, prefix="/api/schedules", tags=["Schedules"])
app.include_router(grade.router, prefix="/api", tags=["Grades"])


_CONFLICT_UI_PATH = Path(__file__).resolve().parent / "static" / "conflict_resolver.html"
_GRADE_UI_PATH = Path(__file__).resolve().parent / "static" / "grade_input.html"


@app.get("/dashboard/conflicts", include_in_schema=False)
def conflict_resolver_dashboard():
    """Menyajikan dashboard web Conflict Resolver UI untuk admin akademik."""
    return FileResponse(_CONFLICT_UI_PATH)


@app.get("/dashboard/grades", include_in_schema=False)
def grade_input_dashboard():
    """Menyajikan form web input nilai & audit trail untuk dosen pengampu."""
    return FileResponse(_GRADE_UI_PATH)
