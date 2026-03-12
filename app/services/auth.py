from __future__ import annotations

import secrets
import time

from app.core.database import db
from app.core.security import get_password_hash, verify_password

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
