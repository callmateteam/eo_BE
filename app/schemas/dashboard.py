from __future__ import annotations

from pydantic import BaseModel


class ProjectItem(BaseModel):
    """프로젝트 리스트 아이템"""

    id: str
    title: str
    character_name: str
    character_image: str
    created_at: str


class TrendKeyword(BaseModel):
    """트렌드 키워드 아이템"""

    rank: int
    keyword: str
    traffic: str


class DashboardResponse(BaseModel):
    """대시보드 응답"""

    recent_projects: list[ProjectItem]
    trending_keywords: list[TrendKeyword]
