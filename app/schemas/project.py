"""프로젝트 관련 스키마"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.dashboard import STATUS_LABEL, STATUS_PROGRESS, ProjectStatus


class ProjectCreateRequest(BaseModel):
    """프로젝트 생성 요청"""

    title: str = Field(min_length=1, max_length=100, description="프로젝트 제목")
    keyword: str = Field(default="", max_length=100, description="키워드")
    character_id: str = Field(description="캐릭터 ID")


class ProjectCreateResponse(BaseModel):
    """프로젝트 생성 응답"""

    id: str
    title: str
    status: str = "CREATED"
    message: str = "프로젝트가 생성되었습니다."


class ProjectDetailResponse(BaseModel):
    """프로젝트 상세 응답"""

    id: str
    title: str
    keyword: str
    character_id: str
    character_name: str
    character_image: str
    status: ProjectStatus
    status_label: str
    progress: int
    created_at: str
    updated_at: str


class ProjectListItem(BaseModel):
    """프로젝트 목록 항목"""

    id: str
    title: str
    character_id: str
    character_name: str
    character_image: str
    status: ProjectStatus
    status_label: str
    progress: int
    created_at: str


class ProjectListResponse(BaseModel):
    """프로젝트 목록 응답"""

    projects: list[ProjectListItem]
    total: int


def project_to_item(p: object) -> dict:
    """프로젝트 DB 레코드 → dict 변환"""
    status = p.status
    ps = ProjectStatus(status) if status in ProjectStatus._value2member_map_ else None
    return {
        "id": p.id,
        "title": p.title,
        "keyword": getattr(p, "keyword", ""),
        "character_id": p.characterId,
        "character_name": p.character.name if p.character else "",
        "character_image": (p.character.thumbnailUrl if p.character else ""),
        "status": status,
        "status_label": STATUS_LABEL.get(ps, "알 수 없음") if ps else "알 수 없음",
        "progress": STATUS_PROGRESS.get(ps, 0) if ps else 0,
        "created_at": p.createdAt.isoformat(),
        "updated_at": p.updatedAt.isoformat() if hasattr(p, "updatedAt") else "",
    }
