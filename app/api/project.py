"""프로젝트 API 라우터"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.core.database import db
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
    # 캐릭터 존재 확인
    char = await db.character.find_unique(where={"id": req.character_id})
    if not char:
        raise HTTPException(status_code=400, detail="캐릭터를 찾을 수 없습니다")

    record = await db.project.create(
        data={
            "title": req.title,
            "keyword": req.keyword,
            "characterId": req.character_id,
            "userId": current_user["id"],
        }
    )
    return ProjectCreateResponse(id=record.id, title=record.title)


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
    records = await db.project.find_many(
        where={"userId": current_user["id"]},
        order={"createdAt": "desc"},
        take=100,
        include={"character": True},
    )
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
    record = await db.project.find_first(
        where={"id": project_id, "userId": current_user["id"]},
        include={"character": True},
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
    record = await db.project.find_first(
        where={"id": project_id, "userId": current_user["id"]},
    )
    if not record:
        raise HTTPException(
            status_code=404, detail="프로젝트를 찾을 수 없습니다"
        )
    await db.project.delete(where={"id": project_id})
