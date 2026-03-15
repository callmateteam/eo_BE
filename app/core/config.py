from __future__ import annotations

import logging

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    PROJECT_NAME: str = "EO Backend"
    VERSION: str = "0.1.0"
    DEBUG: bool = False

    DATABASE_URL: str = "postgresql://localhost:5432/eo"
    SECRET_KEY: str = "change-me-in-production"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    COOKIE_SECURE: bool | None = None  # None이면 DEBUG 기반 자동 결정
    COOKIE_SAMESITE: str = "none"  # 크로스 도메인: "none", 같은 도메인: "lax"
    COOKIE_DOMAIN: str | None = None

    ALLOWED_ORIGINS: list[str] = [
        "http://localhost:3000",
        "https://eo-fe-eight.vercel.app",
        "https://d2aad86kvspq0l.cloudfront.net",
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

    # Google Veo (영상 생성)
    GOOGLE_API_KEY: str = ""
    VEO_MODEL: str = "veo-2.0-generate-001"

    # S3
    S3_BUCKET: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @property
    def cookie_secure_resolved(self) -> bool:
        """COOKIE_SECURE가 None이면 DEBUG 기반 자동 결정

        크로스 도메인(SameSite=None)은 Secure=True 필수 (브라우저 요구사항).
        로컬 개발(DEBUG=True)에서는 False 허용.
        """
        if self.COOKIE_SECURE is not None:
            return self.COOKIE_SECURE
        return not self.DEBUG

    @property
    def cookie_samesite_resolved(self) -> str:
        """SameSite 값 결정

        크로스 도메인(프론트 Vercel ↔ 백엔드 AWS): "none" 필수.
        로컬 개발(같은 localhost): "lax"로 충분.
        """
        return self.COOKIE_SAMESITE


settings = Settings()

# SECRET_KEY 기본값 경고
if settings.SECRET_KEY == "change-me-in-production" and not settings.DEBUG:
    logging.getLogger(__name__).warning(
        "SECRET_KEY가 기본값입니다. 프로덕션에서는 반드시 변경하세요!"
    )

# SameSite=None인데 Secure=False인 경우 경고
if settings.cookie_samesite_resolved == "none" and not settings.cookie_secure_resolved:
    logging.getLogger(__name__).warning(
        "SameSite=None은 Secure=True가 필수입니다. "
        "브라우저가 쿠키를 거부합니다. COOKIE_SECURE=true를 설정하세요."
    )
