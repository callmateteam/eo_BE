from __future__ import annotations

import secrets
import time
from datetime import timedelta

from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

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


async def create_user(name: str, username: str, password: str) -> dict:
    """새 유저 생성"""
    hashed_password = get_password_hash(password)
    user = await db.user.create(
        data={
            "name": name,
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


async def get_user_profile(user_id: str) -> dict | None:
    """유저 프로필 + 소셜 연동 상태 조회"""
    user = await db.user.find_unique(where={"id": user_id})
    if not user:
        return None

    return {
        "id": user.id,
        "name": user.name,
        "username": user.username,
        "email": user.email,
        "profile_image": user.profileImage,
        "social": {
            "youtube": bool(user.googleRefreshToken),
            "tiktok": bool(user.tiktokId),
            "instagram": bool(user.instagramId),
        },
        "created_at": user.createdAt.isoformat(),
    }


def verify_google_id_token(token: str) -> dict:
    """구글 id_token 검증 → 유저 정보 반환

    Returns:
        {"sub": google_id, "email": email, "name": name, "picture": picture_url}

    Raises:
        ValueError: 토큰 검증 실패
    """
    id_info = google_id_token.verify_oauth2_token(
        token,
        google_requests.Request(),
        settings.GOOGLE_CLIENT_ID,
    )
    return {
        "sub": id_info["sub"],
        "email": id_info.get("email"),
        "name": id_info.get("name"),
        "picture": id_info.get("picture"),
    }


async def google_login_or_create(google_info: dict) -> dict:
    """구글 로그인: 기존 유저면 로그인, 없으면 자동 생성

    Returns:
        {"id": user_id, "username": username, "email": email, "is_new_user": bool}
    """
    google_id = google_info["sub"]
    email = google_info.get("email")

    # 1) googleId로 기존 유저 찾기
    user = await db.user.find_unique(where={"googleId": google_id})
    if user:
        return {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "is_new_user": False,
        }

    # 2) email로 기존 유저 찾기 (이메일 매칭 → 자동 연동)
    if email:
        user = await db.user.find_unique(where={"email": email})
        if user:
            await db.user.update(
                where={"id": user.id},
                data={
                    "googleId": google_id,
                    "profileImage": google_info.get("picture"),
                },
            )
            return {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "is_new_user": False,
            }

    # 3) 새 유저 생성 (구글 계정 기반)
    # username: 이메일 앞부분 + 랜덤 4자리
    base_name = (email or "user").split("@")[0][:16]
    suffix = secrets.token_hex(2)
    username = f"{base_name}_{suffix}"

    user = await db.user.create(
        data={
            "name": google_info.get("name", ""),
            "username": username,
            "password": "",
            "email": email,
            "googleId": google_id,
            "profileImage": google_info.get("picture"),
        }
    )
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "is_new_user": True,
    }


async def link_google_account(user_id: str, google_info: dict) -> dict:
    """기존 계정에 구글 연동

    Raises:
        ValueError: 이미 다른 계정에 연동된 구글 계정
    """
    google_id = google_info["sub"]
    email = google_info.get("email")

    # 이미 다른 유저에 연동된 구글 계정인지 확인
    existing = await db.user.find_unique(where={"googleId": google_id})
    if existing and existing.id != user_id:
        raise ValueError("이 구글 계정은 이미 다른 사용자에 연동되어 있습니다.")

    update_data: dict = {
        "googleId": google_id,
        "profileImage": google_info.get("picture"),
    }
    if email:
        update_data["email"] = email

    await db.user.update(where={"id": user_id}, data=update_data)
    return {"email": email or ""}
