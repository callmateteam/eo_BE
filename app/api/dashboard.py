from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.deps import get_current_user
from app.schemas.dashboard import DashboardResponse, ProjectItem, TrendKeyword
from app.services.dashboard import get_recent_projects
from app.services.trending import fetch_trending_keywords

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("", response_model=DashboardResponse)
async def get_dashboard(current_user: dict = Depends(get_current_user)):
    """대시보드 조회 - 최근 프로젝트 + 한국 실시간 인기 검색어"""
    projects_raw = await get_recent_projects(current_user["id"])
    trending_raw = await fetch_trending_keywords(max_results=10)

    recent_projects = [ProjectItem(**p) for p in projects_raw]
    trending_keywords = [TrendKeyword(**t) for t in trending_raw]

    return DashboardResponse(
        recent_projects=recent_projects,
        trending_keywords=trending_keywords,
    )
