from __future__ import annotations

import secrets
import time
from datetime import timedelta

from app.core.config import settings
from app.core.database import db
from app.core.security import create_refresh_token_value, get_password_hash, verify_password
from app.core.timezone import now_kst

# 아이디 검증 토큰 임시 저장소 (프로덕션에서는 Redis 사용 권장)
_verification_tokens: dict[str, dict] = {}

# 토큰 만료 시간 (5분)
VERIFICATION_TOKEN_EXPIRE_SECONDS = 300


def create_verification_token(username: str) -> str:
    """아이디 검증 완료 시 토큰 생성"""
    token = secrets.token_urlsafe(32)
    _verification_tokens[token] = {
        "username": username,
        "created_at": time.time(),
    }
    return token


def validate_verification_token(token: str, username: str) -> bool:
    """검증 토큰이 유효한지 확인"""
    data = _verification_tokens.get(token)
    if not data:
        return False

    if data["username"] != username:
        return False

    elapsed = time.time() - data["created_at"]
    if elapsed > VERIFICATION_TOKEN_EXPIRE_SECONDS:
        _verification_tokens.pop(token, None)
        return False

    return True


def consume_verification_token(token: str) -> None:
    """사용된 토큰 제거"""
    _verification_tokens.pop(token, None)


async def check_username_available(username: str) -> bool:
    """아이디 중복 확인"""
    user = await db.user.find_unique(where={"username": username})
    return user is None


async def create_user(username: str, password: str) -> dict:
    """새 유저 생성"""
    hashed_password = get_password_hash(password)
    user = await db.user.create(
        data={
            "username": username,
            "password": hashed_password,
        }
    )
    return {"id": user.id, "username": user.username}


async def authenticate_user(username: str, password: str) -> dict | None:
    """유저 인증 (로그인)"""
    user = await db.user.find_unique(where={"username": username})
    if not user:
        return None

    if not verify_password(password, user.password):
        return None

    return {"id": user.id, "username": user.username}


async def save_refresh_token(user_id: str) -> str:
    """리프레시 토큰 생성 후 DB 저장"""
    token_value = create_refresh_token_value()
    expires_at = now_kst() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

    await db.refreshtoken.create(
        data={
            "token": token_value,
            "userId": user_id,
            "expiresAt": expires_at,
        }
    )
    return token_value


async def verify_refresh_token(token: str) -> dict | None:
    """리프레시 토큰 검증 - 유효하면 유저 정보 반환"""
    record = await db.refreshtoken.find_unique(
        where={"token": token},
        include={"user": True},
    )
    if not record:
        return None

    if record.expiresAt < now_kst():
        await db.refreshtoken.delete(where={"id": record.id})
        return None

    return {"id": record.user.id, "username": record.user.username}


async def revoke_refresh_token(token: str) -> None:
    """리프레시 토큰 폐기"""
    try:
        await db.refreshtoken.delete(where={"token": token})
    except Exception:
        pass


async def revoke_all_user_tokens(user_id: str) -> None:
    """유저의 모든 리프레시 토큰 폐기 (전체 로그아웃)"""
    await db.refreshtoken.delete_many(where={"userId": user_id})
