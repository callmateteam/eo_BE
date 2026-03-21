"""프로젝트 API 라우터"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from app.core.deps import get_current_user
from app.schemas.auth import ErrorResponse
from app.schemas.project import (
    EnrichedIdeaConfirmResponse,
    EnrichedIdeaData,
    EnrichedIdeaUpdateRequest,
    IdeaEnrichRequest,
    IdeaEnrichResponse,
    ProjectCreateRequest,
    ProjectCreateResponse,
    ProjectDetailResponse,
    ProjectListItem,
    ProjectListResponse,
    ProjectUpdateRequest,
    project_to_item,
)
from app.services.idea_enrichment import enrich_idea
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
from app.services.project import (
    update_project as svc_update_project,
)

logger = logging.getLogger(__name__)

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
    """새 프로젝트 생성 (경로 A: 프리셋 캐릭터 / 경로 B: 커스텀 캐릭터)"""
    try:
        result = await svc_create_project(
            title=req.title,
            keyword=req.keyword,
            character_id=req.character_id,
            custom_character_id=req.custom_character_id,
            user_id=current_user["id"],
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None

    return ProjectCreateResponse(
        id=result["id"],
        title=result["title"],
        current_stage=result["current_stage"],
    )


@router.patch(
    "/{project_id}",
    response_model=ProjectDetailResponse,
    summary="프로젝트 수정 (단계별 데이터 저장 + 자동 단계 진행)",
    responses={
        400: {"model": ErrorResponse, "description": "단계 조건 미충족 / 잘못된 참조"},
        401: {"model": ErrorResponse, "description": "인증 필요"},
        404: {"model": ErrorResponse, "description": "프로젝트 없음"},
    },
)
async def update_project(
    project_id: str,
    req: ProjectUpdateRequest,
    current_user: dict = Depends(get_current_user),
) -> ProjectDetailResponse:
    """프로젝트 수정 (단계별 데이터 저장)"""
    try:
        updated = await svc_update_project(
            project_id=project_id,
            user_id=current_user["id"],
            **req.model_dump(exclude_none=True),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    if not updated:
        raise HTTPException(status_code=404, detail="프로젝트를 찾을 수 없습니다")
    return ProjectDetailResponse(**project_to_item(updated))


@router.post(
    "/{project_id}/enrich-idea",
    response_model=IdeaEnrichResponse,
    summary="아이디어 구체화 (GPT가 배경/분위기/캐릭터/스토리로 구조화)",
    responses={
        400: {"model": ErrorResponse, "description": "아이디어 없음 / GPT 실패"},
        401: {"model": ErrorResponse, "description": "인증 필요"},
        404: {"model": ErrorResponse, "description": "프로젝트 없음"},
    },
)
async def enrich_project_idea(
    project_id: str,
    req: IdeaEnrichRequest,
    current_user: dict = Depends(get_current_user),
) -> IdeaEnrichResponse:
    """2단계 아이디어를 GPT로 구체화한다.

    자연어 아이디어를 배경, 분위기, 메인 캐릭터, 보조 캐릭터, 스토리로 분해한다.
    결과를 확인 후 수정하거나 확정할 수 있다.
    """
    # 프로젝트 존재 확인 (캐릭터 정보 포함)
    record = await svc_get_project(project_id=project_id, user_id=current_user["id"])
    if not record:
        raise HTTPException(status_code=404, detail="프로젝트를 찾을 수 없습니다")

    # 캐릭터 이름/설명 추출
    char_name = ""
    char_desc = ""
    if record.character:
        char_name = record.character.name
        char_desc = record.character.description
    elif hasattr(record, "customCharacter") and record.customCharacter:
        char_name = record.customCharacter.name
        char_desc = record.customCharacter.description

    try:
        enriched = await enrich_idea(
            req.idea,
            character_name=char_name,
            character_desc=char_desc,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None

    return IdeaEnrichResponse(enriched=EnrichedIdeaData(**enriched))


@router.post(
    "/{project_id}/confirm-enriched-idea",
    response_model=EnrichedIdeaConfirmResponse,
    summary="구체화된 아이디어 확정 (수정 반영 후 3단계 진행)",
    responses={
        400: {"model": ErrorResponse, "description": "유효하지 않은 데이터"},
        401: {"model": ErrorResponse, "description": "인증 필요"},
        404: {"model": ErrorResponse, "description": "프로젝트 없음"},
    },
)
async def confirm_enriched_idea(
    project_id: str,
    req: EnrichedIdeaUpdateRequest,
    current_user: dict = Depends(get_current_user),
) -> EnrichedIdeaConfirmResponse:
    """사용자가 수정한 구체화 아이디어를 확정하고 3단계로 진행한다.

    프론트에서 enrich-idea 응답을 편집 UI에 표시하고,
    사용자가 수정한 값을 이 API로 보내 확정한다.
    """
    record = await svc_get_project(project_id=project_id, user_id=current_user["id"])
    if not record:
        raise HTTPException(status_code=404, detail="프로젝트를 찾을 수 없습니다")

    # 기존 enrichedIdea가 있으면 그 위에 부분 업데이트
    _raw = getattr(record, "enrichedIdea", None)
    existing: dict = _raw if isinstance(_raw, dict) else {}
    enriched_data = {
        "background": req.background if req.background is not None
        else existing.get("background", ""),
        "mood": req.mood if req.mood is not None else existing.get("mood", ""),
        "main_character": req.main_character if req.main_character is not None
        else existing.get("main_character", ""),
        "supporting_characters": (
            req.supporting_characters
            if req.supporting_characters is not None
            else existing.get("supporting_characters", [])
        ),
        "story": req.story if req.story is not None else existing.get("story", ""),
    }

    # 필수 필드 검증
    if not enriched_data["background"] or not enriched_data["story"]:
        raise HTTPException(status_code=400, detail="배경과 스토리는 필수입니다")

    try:
        updated = await svc_update_project(
            project_id=project_id,
            user_id=current_user["id"],
            enriched_idea=enriched_data,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    except Exception:
        logger.exception("confirm_enriched_idea 처리 중 오류: project_id=%s", project_id)
        raise HTTPException(status_code=500, detail="서버 오류가 발생했습니다") from None

    if not updated:
        raise HTTPException(status_code=404, detail="프로젝트를 찾을 수 없습니다")

    return EnrichedIdeaConfirmResponse(
        id=updated.id,
        current_stage=updated.currentStage,
        enriched_idea=EnrichedIdeaData(**enriched_data),
    )


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
    record = await svc_get_project(project_id=project_id, user_id=current_user["id"])
    if not record:
        raise HTTPException(status_code=404, detail="프로젝트를 찾을 수 없습니다")
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
    deleted = await svc_delete_project(project_id=project_id, user_id=current_user["id"])
    if not deleted:
        raise HTTPException(status_code=404, detail="프로젝트를 찾을 수 없습니다")
