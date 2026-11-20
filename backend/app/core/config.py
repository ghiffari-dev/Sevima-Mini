from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "PMB Academic System"
    DATABASE_URL: str = "sqlite:///./pmb.db"
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

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
