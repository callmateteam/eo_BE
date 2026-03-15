"""프로젝트 API 라우터"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.core.deps import get_current_user
from app.schemas.auth import ErrorResponse
from app.schemas.project import (
    ProjectCreateRequest,
    ProjectCreateResponse,
    ProjectDetailResponse,
    ProjectListItem,
    ProjectListResponse,
    project_to_item,
)
from app.services.project import (
    create_project as svc_create_project,
)
from app.services.project import (
    delete_project as svc_delete_project,
)
from app.services.project import (
    get_project as svc_get_project,
)
from app.services.project import (
    list_projects as svc_list_projects,
)

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post(
    "",
    response_model=ProjectCreateResponse,
    status_code=201,
    summary="프로젝트 생성",
    responses={
        401: {"model": ErrorResponse, "description": "인증 필요"},
        400: {"model": ErrorResponse, "description": "캐릭터 없음"},
    },
)
async def create_project(
    req: ProjectCreateRequest,
    current_user: dict = Depends(get_current_user),
) -> ProjectCreateResponse:
    """새 프로젝트 생성"""
    try:
        result = await svc_create_project(
            title=req.title,
            keyword=req.keyword,
            character_id=req.character_id,
            user_id=current_user["id"],
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None

    return ProjectCreateResponse(id=result["id"], title=result["title"])


@router.get(
    "",
    response_model=ProjectListResponse,
    summary="내 프로젝트 목록",
    responses={
        401: {"model": ErrorResponse, "description": "인증 필요"},
    },
)
async def list_projects(
    current_user: dict = Depends(get_current_user),
) -> ProjectListResponse:
    """내 프로젝트 전체 목록 (최신순, 진행중 포함)"""
    records = await svc_list_projects(user_id=current_user["id"])
    items = [ProjectListItem(**project_to_item(r)) for r in records]
    return ProjectListResponse(projects=items, total=len(items))


@router.get(
    "/{project_id}",
    response_model=ProjectDetailResponse,
    summary="프로젝트 상세 조회",
    responses={
        401: {"model": ErrorResponse, "description": "인증 필요"},
        404: {"model": ErrorResponse, "description": "프로젝트 없음"},
    },
)
async def get_project(
    project_id: str,
    current_user: dict = Depends(get_current_user),
) -> ProjectDetailResponse:
    """프로젝트 상세 조회 (본인 소유만)"""
    record = await svc_get_project(
        project_id=project_id, user_id=current_user["id"]
    )
    if not record:
        raise HTTPException(
            status_code=404, detail="프로젝트를 찾을 수 없습니다"
        )
    return ProjectDetailResponse(**project_to_item(record))


@router.delete(
    "/{project_id}",
    status_code=204,
    summary="프로젝트 삭제",
    responses={
        401: {"model": ErrorResponse, "description": "인증 필요"},
        404: {"model": ErrorResponse, "description": "프로젝트 없음"},
    },
)
async def delete_project(
    project_id: str,
    current_user: dict = Depends(get_current_user),
) -> None:
    """프로젝트 삭제 (본인 소유만)"""
    deleted = await svc_delete_project(
        project_id=project_id, user_id=current_user["id"]
    )
    if not deleted:
        raise HTTPException(
            status_code=404, detail="프로젝트를 찾을 수 없습니다"
        )
