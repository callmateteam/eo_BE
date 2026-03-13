from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    PROJECT_NAME: str = "EO Backend"
    VERSION: str = "0.1.0"
    DEBUG: bool = False

    DATABASE_URL: str = "postgresql+asyncpg://localhost:5432/eo"
    SECRET_KEY: str = "change-me-in-production"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    COOKIE_SECURE: bool = False  # 프로덕션에서는 True (HTTPS)
    COOKIE_DOMAIN: str | None = None

    ALLOWED_ORIGINS: list[str] = [
        "http://localhost:3000",
        "https://eo-fe-eight.vercel.app",
    ]

    # YouTube
    YOUTUBE_API_KEY: str = ""

    # AWS
    AWS_REGION: str = "ap-northeast-2"
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""

    # Google OAuth
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""

    # Kling
    KLING_ACCESS_KEY: str = ""
    KLING_SECRET_KEY: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
