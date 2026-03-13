from __future__ import annotations

import re

from pydantic import BaseModel, field_validator


class UsernameValidateRequest(BaseModel):
    username: str

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        v = v.strip()

        if not v:
            raise ValueError("아이디를 입력해주세요.")

        if len(v) < 5:
            raise ValueError("아이디는 최소 5자 이상이어야 합니다.")

        if len(v) > 20:
            raise ValueError("아이디는 최대 20자까지 가능합니다.")

        if not re.match(r"^[a-zA-Z0-9]+$", v):
            raise ValueError("아이디는 영문과 숫자만 사용할 수 있습니다.")

        if not re.search(r"[a-zA-Z]", v):
            raise ValueError(
                "아이디에 영문은 최소 1자 이상 포함해야 합니다. 숫자만으로는 사용할 수 없습니다."
            )

        return v


class UsernameValidateResponse(BaseModel):
    available: bool
    username: str
    verification_token: str | None = None
    message: str


class SignupRequest(BaseModel):
    name: str
    username: str
    password: str
    verification_token: str

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("이름을 입력해주세요.")
        if len(v) > 30:
            raise ValueError("이름은 최대 30자까지 가능합니다.")
        return v

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        v = v.strip()

        if not v:
            raise ValueError("아이디를 입력해주세요.")

        if len(v) < 5:
            raise ValueError("아이디는 최소 5자 이상이어야 합니다.")

        if len(v) > 20:
            raise ValueError("아이디는 최대 20자까지 가능합니다.")

        if not re.match(r"^[a-zA-Z0-9]+$", v):
            raise ValueError("아이디는 영문과 숫자만 사용할 수 있습니다.")

        if not re.search(r"[a-zA-Z]", v):
            raise ValueError(
                "아이디에 영문은 최소 1자 이상 포함해야 합니다. 숫자만으로는 사용할 수 없습니다."
            )

        return v

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("비밀번호는 8자 이상이어야 합니다.")

        if len(v) >= 64:
            raise ValueError("비밀번호는 64자 미만이어야 합니다.")

        if not re.search(r"[a-zA-Z]", v):
            raise ValueError("비밀번호에 영문을 포함해야 합니다.")

        if not re.search(r"[0-9]", v):
            raise ValueError("비밀번호에 숫자를 포함해야 합니다.")

        if not re.search(r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>/?`~]", v):
            raise ValueError("비밀번호에 특수문자를 최소 1자 이상 포함해야 합니다.")

        return v

    @field_validator("verification_token")
    @classmethod
    def validate_verification_token(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("아이디 검증 토큰이 필요합니다. 먼저 아이디 검증 API를 호출해주세요.")
        return v.strip()


class SignupResponse(BaseModel):
    id: str
    username: str
    message: str


class LoginRequest(BaseModel):
    username: str
    password: str

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("아이디를 입력해주세요.")
        return v.strip()

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if not v:
            raise ValueError("비밀번호를 입력해주세요.")
        return v


class LoginResponse(BaseModel):
    user_id: str
    username: str
    message: str


class ErrorDetail(BaseModel):
    field: str | None = None
    message: str


class ErrorResponse(BaseModel):
    detail: str
    errors: list[ErrorDetail] = []


class GoogleLoginRequest(BaseModel):
    """구글 로그인 요청 (프론트에서 받은 id_token)"""

    id_token: str


class GoogleLoginResponse(BaseModel):
    """구글 로그인 응답"""

    user_id: str
    username: str
    email: str | None = None
    is_new_user: bool = False
    message: str


class GoogleLinkRequest(BaseModel):
    """기존 계정에 구글 연동 요청"""

    id_token: str


class GoogleLinkResponse(BaseModel):
    """구글 연동 응답"""

    email: str
    message: str


class SocialConnections(BaseModel):
    """소셜 연동 상태"""

    youtube: bool = False
    tiktok: bool = False
    instagram: bool = False


class MeResponse(BaseModel):
    """내 정보 응답"""

    id: str
    name: str
    username: str
    email: str | None = None
    profile_image: str | None = None
    social: SocialConnections
    created_at: str
