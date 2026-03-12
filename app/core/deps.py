from __future__ import annotations

from fastapi import HTTPException, Request, status
from jose import JWTError, jwt

from app.core.config import settings
from app.core.database import db
from app.core.security import ACCESS_TOKEN_COOKIE, ALGORITHM


async def get_current_user(request: Request) -> dict:
    """쿠키의 access_token에서 현재 로그인 유저 정보 추출"""
    token = request.cookies.get(ACCESS_TOKEN_COOKIE)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="로그인이 필요합니다.",
        )

    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str | None = payload.get("sub")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="유효하지 않은 인증 토큰입니다.",
            )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="인증 토큰이 만료되었거나 유효하지 않습니다.",
        ) from None

    user = await db.user.find_unique(where={"id": user_id})
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="사용자를 찾을 수 없습니다.",
        )

    return {"id": user.id, "username": user.username}
