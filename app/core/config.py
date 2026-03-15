from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    PROJECT_NAME: str = "EO Backend"
    VERSION: str = "0.1.0"
    DEBUG: bool = False

    DATABASE_URL: str = "postgresql://localhost:5432/eo"
    SECRET_KEY: str = "change-me-in-production"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    COOKIE_SECURE: bool = False  # 프로덕션에서는 True (HTTPS)
    COOKIE_DOMAIN: str | None = None

    ALLOWED_ORIGINS: list[str] = [
        "http://localhost:3000",
        "https://eo-fe-eight.vercel.app",
        "https://d2phq2ghco7tx0.cloudfront.net",
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

    # OpenAI (GPT-4o Vision - 커스텀 캐릭터 분석)
    OPENAI_API_KEY: str = ""

    # Google Veo (영상 생성) — deprecated, Kling으로 전환
    GOOGLE_API_KEY: str = ""
    VEO_MODEL: str = "veo-2.0-generate-001"

    # Kling AI (kie.ai 경유 영상 생성)
    KLING_API_KEY: str = ""
    KLING_MODEL: str = "pro-text-to-video"
    KLING_I2V_MODEL: str = "pro-image-to-video"
    KLING_BASE_URL: str = "https://kling3api.com"
    KLING_POLL_INTERVAL: int = 5
    KLING_MAX_WAIT: int = 300

    # S3
    S3_BUCKET: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
