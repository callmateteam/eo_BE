from __future__ import annotations

import secrets
from datetime import timedelta

from fastapi import Response
from jose import jwt
from passlib.context import CryptContext

from app.core.config import settings
from app.core.timezone import now_kst

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

ALGORITHM = "HS256"

# 쿠키 키 이름
ACCESS_TOKEN_COOKIE = "access_token"
REFRESH_TOKEN_COOKIE = "refresh_token"


def create_access_token(subject: str, expires_delta: timedelta | None = None) -> str:
    """액세스 토큰 생성 (JWT)"""
    expire = now_kst() + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode = {"exp": expire, "sub": str(subject), "type": "access"}
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token_value() -> str:
    """리프레시 토큰 값 생성 (opaque random string)"""
    return secrets.token_urlsafe(48)


def set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    """응답에 액세스/리프레시 토큰 쿠키 설정"""
    response.set_cookie(
        key=ACCESS_TOKEN_COOKIE,
        value=access_token,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="none",
        domain=settings.COOKIE_DOMAIN,
        path="/",
    )
    response.set_cookie(
        key=REFRESH_TOKEN_COOKIE,
        value=refresh_token,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="none",
        domain=settings.COOKIE_DOMAIN,
        path="/api/auth",
    )


def clear_auth_cookies(response: Response) -> None:
    """인증 쿠키 삭제"""
    response.delete_cookie(
        key=ACCESS_TOKEN_COOKIE,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="none",
        domain=settings.COOKIE_DOMAIN,
        path="/",
    )
    response.delete_cookie(
        key=REFRESH_TOKEN_COOKIE,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="none",
        domain=settings.COOKIE_DOMAIN,
        path="/api/auth",
    )


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)
