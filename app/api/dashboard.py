from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.deps import get_current_user
from app.schemas.auth import ErrorResponse
from app.schemas.dashboard import (
    CreationTrendItem,
    DashboardResponse,
    ProjectItem,
    RecentCharacterItem,
    TrendKeyword,
)
from app.services.creation_trend import get_creation_trends
from app.services.dashboard import get_recent_characters, get_recent_projects
from app.services.trending import fetch_trending_keywords

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get(
    "",
    response_model=DashboardResponse,
    summary="대시보드 조회",
    responses={
        401: {"model": ErrorResponse, "description": "인증 필요 (쿠키 없음/만료)"},
    },
)
async def get_dashboard(current_user: dict = Depends(get_current_user)):
    """대시보드 데이터 조회

    - recent_projects: 최근 프로젝트 목록 (최신순)
    - recent_characters: 사용자가 사용한 캐릭터 목록 (없으면 null)
    - trending_keywords: 실시간 트렌드 키워드
    """
    projects_raw = await get_recent_projects(current_user["id"])
    characters_raw = await get_recent_characters(current_user["id"])
    trending_raw = await fetch_trending_keywords(max_results=5)
    creation_raw = await get_creation_trends(limit=10)

    recent_projects = [ProjectItem(**p) for p in projects_raw]
    recent_characters = (
        [RecentCharacterItem(**c) for c in characters_raw] if characters_raw else None
    )
    trending_keywords = [TrendKeyword(**t) for t in trending_raw]
    creation_trends = [CreationTrendItem(**c) for c in creation_raw]

    return DashboardResponse(
        recent_projects=recent_projects,
        recent_characters=recent_characters,
        trending_keywords=trending_keywords,
        creation_trends=creation_trends,
    )
