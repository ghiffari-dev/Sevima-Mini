import sqlite3
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.models.krs import KRSError

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


DB_PATH = "backend/pmb.db"

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

from app.routers import krs, pmb
app.include_router(pmb.router, prefix="/api/pmb", tags=["PMB"])
app.include_router(krs.router, prefix="/api/krs", tags=["KRS"])



