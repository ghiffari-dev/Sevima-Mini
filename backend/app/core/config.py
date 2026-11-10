import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "PMB Academic System"
    DATABASE_URL: str = "sqlite:///./pmb.db"

    class Config:
        env_file = ".env"

settings = Settings()
