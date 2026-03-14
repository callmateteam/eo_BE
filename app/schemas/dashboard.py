from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class ProjectStatus(str, Enum):  # noqa: UP042
    """프로젝트 진행 상태"""

    CREATED = "CREATED"
    SCRIPT_WRITTEN = "SCRIPT_WRITTEN"
    VOICE_GENERATED = "VOICE_GENERATED"
    VIDEO_GENERATED = "VIDEO_GENERATED"
    COMPLETED = "COMPLETED"


# 상태별 진행률 매핑
STATUS_PROGRESS: dict[ProjectStatus, int] = {
    ProjectStatus.CREATED: 0,
    ProjectStatus.SCRIPT_WRITTEN: 25,
    ProjectStatus.VOICE_GENERATED: 50,
    ProjectStatus.VIDEO_GENERATED: 75,
    ProjectStatus.COMPLETED: 100,
}

# 상태별 한글 라벨
STATUS_LABEL: dict[ProjectStatus, str] = {
    ProjectStatus.CREATED: "프로젝트 생성",
    ProjectStatus.SCRIPT_WRITTEN: "스크립트 작성 완료",
    ProjectStatus.VOICE_GENERATED: "음성 생성 완료",
    ProjectStatus.VIDEO_GENERATED: "영상 생성 완료",
    ProjectStatus.COMPLETED: "완료",
}


class ProjectItem(BaseModel):
    """프로젝트 리스트 아이템"""

    id: str
    title: str
    character_id: str
    character_name: str
    character_image: str
    status: ProjectStatus
    status_label: str
    progress: int
    created_at: str


class TrendKeyword(BaseModel):
    """유튜브 트렌드 키워드 아이템"""

    rank: int
    keyword: str
    traffic: str


class CreationTrendItem(BaseModel):
    """플랫폼 내 제작 트렌드 아이템"""

    rank: int
    keyword: str
    count: int


class RecentCharacterItem(BaseModel):
    """최근 사용한 캐릭터 아이템 (프리셋/커스텀 통합)"""

    id: str
    name: str
    name_en: str = ""
    series: str = ""
    category: str
    image_url: str
    thumbnail_url: str
    type: str = "preset"  # "preset" | "custom"
    last_used_at: str


class DashboardResponse(BaseModel):
    """대시보드 응답"""

    recent_projects: list[ProjectItem]
    recent_characters: list[RecentCharacterItem] | None = None
    trending_keywords: list[TrendKeyword]
    creation_trends: list[CreationTrendItem]
