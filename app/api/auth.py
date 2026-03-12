from fastapi import APIRouter, HTTPException, status

from app.core.security import create_access_token
from app.schemas.auth import (
    ErrorDetail,
    ErrorResponse,
    LoginRequest,
    LoginResponse,
    SignupRequest,
    SignupResponse,
    UsernameValidateRequest,
    UsernameValidateResponse,
)
from app.services.auth import (
    authenticate_user,
    check_username_available,
    consume_verification_token,
    create_user,
    create_verification_token,
    validate_verification_token,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/validate-username",
    response_model=UsernameValidateResponse,
    responses={
        400: {"model": ErrorResponse, "description": "유효성 검사 실패"},
        409: {"model": ErrorResponse, "description": "이미 사용 중인 아이디"},
    },
)
async def validate_username(request: UsernameValidateRequest):
    """아이디 유효성 검사 및 중복 확인 API"""
    is_available = await check_username_available(request.username)

    if not is_available:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=ErrorResponse(
                detail="이미 사용 중인 아이디입니다.",
                errors=[
                    ErrorDetail(
                        field="username",
                        message=(
                            f"'{request.username}'은(는) 이미 다른 사용자가 "
                            "사용하고 있습니다. 다른 아이디를 입력해주세요."
                        ),
                    )
                ],
            ).model_dump(),
        )

    token = create_verification_token(request.username)

    return UsernameValidateResponse(
        available=True,
        username=request.username,
        verification_token=token,
        message="사용 가능한 아이디입니다.",
    )


@router.post(
    "/signup",
    response_model=SignupResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"model": ErrorResponse, "description": "유효성 검사 실패"},
        409: {"model": ErrorResponse, "description": "이미 사용 중인 아이디"},
    },
)
async def signup(request: SignupRequest):
    """회원가입 API - 아이디 검증 토큰 필수"""
    if not validate_verification_token(request.verification_token, request.username):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorResponse(
                detail="아이디 검증이 유효하지 않습니다.",
                errors=[
                    ErrorDetail(
                        field="verification_token",
                        message="검증 토큰이 만료되었거나 유효하지 않습니다. "
                        "아이디 검증 API(/api/auth/validate-username)를 다시 호출해주세요.",
                    )
                ],
            ).model_dump(),
        )

    is_available = await check_username_available(request.username)
    if not is_available:
        consume_verification_token(request.verification_token)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=ErrorResponse(
                detail="이미 사용 중인 아이디입니다.",
                errors=[
                    ErrorDetail(
                        field="username",
                        message=(
                            f"'{request.username}'은(는) 검증 후 "
                            "다른 사용자가 먼저 가입했습니다. "
                            "다른 아이디로 다시 시도해주세요."
                        ),
                    )
                ],
            ).model_dump(),
        )

    user = await create_user(request.username, request.password)
    consume_verification_token(request.verification_token)

    return SignupResponse(
        id=user["id"],
        username=user["username"],
        message="회원가입이 완료되었습니다.",
    )


@router.post(
    "/login",
    response_model=LoginResponse,
    responses={
        401: {"model": ErrorResponse, "description": "인증 실패"},
    },
)
async def login(request: LoginRequest):
    """로그인 API"""
    user = await authenticate_user(request.username, request.password)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ErrorResponse(
                detail="로그인에 실패했습니다.",
                errors=[
                    ErrorDetail(
                        field=None,
                        message="아이디 또는 비밀번호가 올바르지 않습니다. 다시 확인해주세요.",
                    )
                ],
            ).model_dump(),
        )

    access_token = create_access_token(subject=user["id"])

    return LoginResponse(
        access_token=access_token,
        user_id=user["id"],
        username=user["username"],
    )
