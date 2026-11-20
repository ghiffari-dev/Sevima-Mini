from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

_BACKEND_DIR = Path(__file__).resolve().parents[2]
_DEFAULT_DB_PATH = (_BACKEND_DIR / "pmb.db").as_posix()


class Settings(BaseSettings):
    PROJECT_NAME: str = "PMB Academic System"
    DATABASE_URL: str = f"sqlite:///{_DEFAULT_DB_PATH}"
    GEMINI_API_KEY: str | None = None
    OPENROUTER_API_KEY: str | None = None
    OPENAI_API_KEY: str | None = None
    AI_MODEL: str | None = None
    ADMIN_DEMO_EMAIL: str = "admin.akademik@sevima.ac.id"
    ADMIN_DEMO_PASSWORD: str = "admin123"
    DOSEN_DEMO_EMAIL: str = "dosen.pengampu@sevima.ac.id"
    DOSEN_DEMO_PASSWORD: str = "dosen123"
    PAYMENT_WEBHOOK_SECRET: str = "sevima-webhook-secret-dev"
    SPP_DEFAULT_AMOUNT: str = "4500000.00"
    SPP_TEKNIK_AMOUNT: str = "5000000.00"
    SPP_EKONOMI_AMOUNT: str = "4000000.00"
    SPP_DUE_DAYS: int = 14
    LATE_FEE_RATE_PER_MONTH: str = "0.02"
    LATE_FEE_MAX_RATE: str = "0.10"
    LATE_FEE_GRACE_DAYS: int = 0
    FINANCE_SCHEDULER_ENABLED: bool = True
    MAHASISWA_DEMO_EMAIL: str = "mahasiswa.demo@sevima.ac.id"
    MAHASISWA_DEMO_PASSWORD: str = "mhs123"
    MAHASISWA_DEMO_NIM: str = "2025001-0101"
    ATTENDANCE_TIMEZONE: str = "Asia/Jakarta"
    ATTENDANCE_QR_ROTATE_SECONDS: int = 120
    ATTENDANCE_QR_GRACE_WINDOWS: int = 1
    ATTENDANCE_OPEN_EARLY_MINUTES: int = 15
    ATTENDANCE_ON_TIME_MINUTES: int = 15
    ATTENDANCE_LATE_MAX_MINUTES: int = 30
    ATTENDANCE_MIN_PERCENT: str = "75"
    ATTENDANCE_TOTAL_PERTEMUAN: int = 14
    ATTENDANCE_GEO_ENABLED: bool = True
    ATTENDANCE_GEOFENCE_RADIUS_M: int = 100
    ATTENDANCE_GEO_MAX_ACCURACY_M: int = 150
    ATTENDANCE_SCAN_RATE_LIMIT: int = 5
    ATTENDANCE_SCAN_RATE_LIMIT_IP: int = 120
    ATTENDANCE_SCAN_RATE_WINDOW_SECONDS: int = 60

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
