"""영상 생성 API 라우터"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.core.deps import get_current_user
from app.schemas.auth import ErrorResponse
from app.schemas.video import (
    VideoGenerateRequest,
    VideoStatusResponse,
    VideoTaskResponse,
)
from app.services.character import get_character_by_id
from app.services.video import get_generator

router = APIRouter(prefix="/api/video", tags=["video"])


@router.post(
    "/generate",
    response_model=VideoTaskResponse,
    responses={
        401: {"model": ErrorResponse, "description": "인증 필요 (쿠키 없음/만료)"},
        404: {"model": ErrorResponse, "description": "캐릭터를 찾을 수 없음"},
        422: {"model": ErrorResponse, "description": "요청 파라미터 유효성 검사 실패"},
        500: {"model": ErrorResponse, "description": "영상 생성 API 호출 실패"},
    },
)
async def generate_video(
    req: VideoGenerateRequest,
    current_user: dict = Depends(get_current_user),
) -> VideoTaskResponse:
    """영상 생성 요청

    캐릭터 ID와 프롬프트를 받아 영상 생성 작업을 시작합니다.
    캐릭터의 veo_prompt + 사용자 prompt를 조합하여 영상 생성 API에 전달합니다.
    """
    # 캐릭터 조회
    character = await get_character_by_id(req.character_id)
    if not character:
        raise HTTPException(status_code=404, detail="캐릭터를 찾을 수 없습니다")

    # 프롬프트 조합: 캐릭터 veo_prompt + 사용자 prompt + 시네마틱 키워드
    cinematic = (
        "cinematic lighting, film grain, shallow depth of field, "
        "shot on 35mm film, natural color grading"
    )
    full_prompt = f"{character['veo_prompt']}, {req.prompt}, {cinematic}"

    generator = get_generator(req.provider.value)

    task_id = await generator.generate(
        prompt=full_prompt,
        image_url=character.get("image_url"),
        duration=req.duration,
        mode=req.mode.value,
        aspect_ratio=req.aspect_ratio.value,
    )

    return VideoTaskResponse(
        task_id=task_id,
        provider=req.provider,
        status="submitted",
    )


@router.get(
    "/status/{provider}/{task_id}",
    response_model=VideoStatusResponse,
    responses={
        401: {"model": ErrorResponse, "description": "인증 필요 (쿠키 없음/만료)"},
        400: {"model": ErrorResponse, "description": "지원하지 않는 provider"},
        500: {"model": ErrorResponse, "description": "상태 조회 API 호출 실패"},
    },
)
async def get_video_status(
    provider: str,
    task_id: str,
    current_user: dict = Depends(get_current_user),
) -> VideoStatusResponse:
    """영상 생성 상태 조회

    provider와 task_id로 영상 생성 작업의 현재 상태를 조회합니다.
    status: submitted → processing → completed / failed
    """
    generator = get_generator(provider)
    result = await generator.get_status(task_id)

    return VideoStatusResponse(
        task_id=task_id,
        provider=provider,
        status=result["status"],
        video_url=result.get("video_url"),
        duration=result.get("duration"),
        error=result.get("error"),
    )
