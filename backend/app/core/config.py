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

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
