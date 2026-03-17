"""YouTube 연동 및 업로드 API"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.deps import get_current_user
from app.schemas.auth import ErrorDetail, ErrorResponse
from app.schemas.youtube import (
    YoutubeConnectRequest,
    YoutubeConnectResponse,
    YoutubeDisconnectResponse,
    YoutubeStatusResponse,
    YoutubeUploadRequest,
    YoutubeUploadResponse,
)
from app.services.youtube import (
    connect_youtube,
    disconnect_youtube,
    upload_to_youtube,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/youtube", tags=["youtube"])


@router.post(
    "/connect",
    response_model=YoutubeConnectResponse,
    summary="YouTube 계정 연동",
    responses={
        400: {"model": ErrorResponse, "description": "인증 코드 교환 실패"},
        401: {"model": ErrorResponse, "description": "로그인 필요"},
    },
)
async def youtube_connect(
    request: YoutubeConnectRequest,
    current_user: dict = Depends(get_current_user),
):
    """YouTube 계정 연동

    프론트에서 Google OAuth consent 후 받은 authorization code를 전달하면:
    1. code → refresh_token 교환
    2. YouTube 채널 정보 조회
    3. refresh_token DB 저장
    """
    try:
        result = await connect_youtube(
            user_id=current_user["id"],
            code=request.code,
            redirect_uri=request.redirect_uri,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorResponse(
                detail=str(e),
                errors=[ErrorDetail(field="code", message=str(e))],
            ).model_dump(),
        ) from None

    return YoutubeConnectResponse(
        channel_title=result["channel_title"],
        message="YouTube 계정이 연동되었습니다.",
    )


@router.delete(
    "/disconnect",
    response_model=YoutubeDisconnectResponse,
    summary="YouTube 연동 해제",
)
async def youtube_disconnect(
    current_user: dict = Depends(get_current_user),
):
    """YouTube 연동 해제 - refresh_token 삭제"""
    await disconnect_youtube(current_user["id"])
    return YoutubeDisconnectResponse(message="YouTube 연동이 해제되었습니다.")


@router.post(
    "/upload/{project_id}",
    response_model=YoutubeUploadResponse,
    summary="프로젝트 영상 YouTube 업로드",
    responses={
        400: {"model": ErrorResponse, "description": "업로드 조건 불충족"},
        401: {"model": ErrorResponse, "description": "로그인 필요"},
    },
)
async def youtube_upload(
    project_id: str,
    request: YoutubeUploadRequest,
    current_user: dict = Depends(get_current_user),
):
    """프로젝트의 최종 영상을 YouTube에 업로드

    - YouTube 연동 필수
    - 최종 영상(finalVideoUrl)이 있어야 함
    - S3에서 다운로드 → YouTube API로 업로드
    """
    try:
        result = await upload_to_youtube(
            user_id=current_user["id"],
            project_id=project_id,
            title=request.title,
            description=request.description,
            tags=request.tags,
            privacy_status=request.privacy_status,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorResponse(
                detail=str(e),
                errors=[ErrorDetail(message=str(e))],
            ).model_dump(),
        ) from None

    return YoutubeUploadResponse(
        youtube_video_id=result["youtube_video_id"],
        youtube_url=result["youtube_url"],
        message="YouTube 업로드가 완료되었습니다.",
    )


@router.get(
    "/upload/{project_id}/status",
    response_model=YoutubeStatusResponse,
    summary="YouTube 업로드 상태 조회",
)
async def youtube_upload_status(
    project_id: str,
    current_user: dict = Depends(get_current_user),
):
    """프로젝트의 YouTube 업로드 상태 조회"""
    from app.core.database import db

    project = await db.project.find_unique(where={"id": project_id})
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="프로젝트를 찾을 수 없습니다.",
        )

    if project.userId != current_user["id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="본인의 프로젝트만 조회할 수 있습니다.",
        )

    return YoutubeStatusResponse(
        status=project.youtubeUploadStatus,
        youtube_video_id=project.youtubeVideoId,
        youtube_url=project.youtubeUrl,
        error=project.youtubeError,
    )
