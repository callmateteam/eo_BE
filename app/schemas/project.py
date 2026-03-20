"""프로젝트 관련 스키마"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.dashboard import STATUS_LABEL, STATUS_PROGRESS, ProjectStatus

STAGE_NAMES = {
    1: "CHARACTER_SELECT",
    2: "IDEA_INPUT",
    3: "IDEA_ENRICHMENT",
    4: "STORYBOARD",
    5: "VIDEO_GENERATION",
}


class ProjectCreateRequest(BaseModel):
    """프로젝트 생성 요청 - 경로 A(기존 캐릭터) 또는 경로 B(커스텀 캐릭터)"""

    title: str = Field(min_length=1, max_length=100, description="프로젝트 제목")
    keyword: str = Field(default="", max_length=100, description="키워드")
    character_id: str | None = Field(default=None, description="프리셋 캐릭터 ID")
    custom_character_id: str | None = Field(default=None, description="커스텀 캐릭터 ID")


class ProjectCreateResponse(BaseModel):
    """프로젝트 생성 응답"""

    id: str
    title: str
    current_stage: int = 1
    status: str = "CREATED"
    message: str = "프로젝트가 생성되었습니다."


class EnrichedIdeaData(BaseModel):
    """GPT가 구조화한 아이디어 데이터"""

    background: str = Field(description="배경 설명")
    mood: str = Field(description="분위기/톤")
    main_character: str = Field(description="메인 캐릭터 묘사")
    supporting_characters: list[str] = Field(default_factory=list, description="보조 캐릭터 목록")
    story: str = Field(description="스토리 요약 (도입-전개-클라이맥스-결말)")


class IdeaEnrichRequest(BaseModel):
    """아이디어 구체화 요청 (2단계 → 3단계)"""

    idea: str = Field(min_length=2, max_length=2000, description="자연어 아이디어")


class IdeaEnrichResponse(BaseModel):
    """아이디어 구체화 응답"""

    enriched: EnrichedIdeaData
    message: str = "아이디어가 구체화되었습니다. 수정 후 확정해주세요."


class EnrichedIdeaUpdateRequest(BaseModel):
    """구조화된 아이디어 수정 요청 (사용자가 직접 편집)"""

    background: str | None = Field(default=None, max_length=500)
    mood: str | None = Field(default=None, max_length=200)
    main_character: str | None = Field(default=None, max_length=500)
    supporting_characters: list[str] | None = None
    story: str | None = Field(default=None, max_length=2000)


class EnrichedIdeaConfirmResponse(BaseModel):
    """구조화된 아이디어 확정 응답"""

    id: str
    current_stage: int
    enriched_idea: EnrichedIdeaData
    message: str = "아이디어가 확정되었습니다. 스토리보드를 생성해주세요."


class ProjectUpdateRequest(BaseModel):
    """프로젝트 수정 요청 (PATCH)"""

    title: str | None = Field(default=None, min_length=1, max_length=100)
    keyword: str | None = Field(default=None, max_length=100)
    character_id: str | None = None
    custom_character_id: str | None = None
    idea: str | None = Field(default=None, max_length=2000)
    enriched_idea: dict | None = Field(default=None, description="구조화된 아이디어 (JSON)")
    storyboard_id: str | None = None
    current_stage: int | None = Field(default=None, ge=1, le=5)


class StageInfo(BaseModel):
    """단계별 상태 정보"""

    stage: int
    name: str
    label: str
    completed: bool
    data: dict | None = None


class ProjectDetailResponse(BaseModel):
    """프로젝트 상세 응답"""

    id: str
    title: str
    keyword: str
    current_stage: int
    stage_name: str
    character_id: str | None
    custom_character_id: str | None
    character_name: str
    character_image: str
    storyboard_id: str | None
    idea: str | None
    enriched_idea: dict | None = None
    stages: list[StageInfo]
    status: ProjectStatus
    status_label: str
    progress: int
    created_at: str
    updated_at: str


class ProjectListItem(BaseModel):
    """프로젝트 목록 항목"""

    id: str
    title: str
    current_stage: int
    stage_name: str
    character_id: str | None
    custom_character_id: str | None
    character_name: str
    character_image: str
    thumbnail_url: str | None
    status: ProjectStatus
    status_label: str
    progress: int
    created_at: str
    updated_at: str


class ProjectListResponse(BaseModel):
    """프로젝트 목록 응답"""

    projects: list[ProjectListItem]
    total: int


def _get_character_info(p: object) -> tuple[str, str]:
    """프로젝트에서 캐릭터 이름/이미지를 추출한다 (프리셋 또는 커스텀)."""
    if p.character:
        return p.character.name, p.character.thumbnailUrl or ""
    if hasattr(p, "customCharacter") and p.customCharacter:
        return p.customCharacter.name, p.customCharacter.imageUrl1 or ""
    return "", ""


def _get_thumbnail(p: object) -> str | None:
    """프로젝트 썸네일: 스토리보드 heroFrame 또는 첫 씬 이미지."""
    sb = getattr(p, "storyboard", None)
    if not sb:
        return None
    if sb.heroFrameUrl:
        return sb.heroFrameUrl
    scenes = getattr(sb, "scenes", None)
    if scenes:
        sorted_scenes = sorted(scenes, key=lambda s: s.sceneOrder)
        for scene in sorted_scenes:
            if scene.imageUrl:
                return scene.imageUrl
    return None


STAGE_LABELS = {
    1: "캐릭터 선택",
    2: "아이디어 입력",
    3: "아이디어 구체화",
    4: "스토리보드",
    5: "영상 생성",
}


def _build_stages(p: object, char_name: str, char_image: str) -> list[dict]:
    """프로젝트의 5단계 상태 + 데이터를 빌드한다."""
    current = getattr(p, "currentStage", 1)
    enriched = getattr(p, "enrichedIdea", None)
    storyboard_id = getattr(p, "storyboardId", None)

    stages = [
        {
            "stage": 1,
            "name": "CHARACTER_SELECT",
            "label": STAGE_LABELS[1],
            "completed": current >= 1,
            "data": {
                "character_id": p.characterId,
                "custom_character_id": getattr(p, "customCharacterId", None),
                "character_name": char_name,
                "character_image": char_image,
            } if (p.characterId or getattr(p, "customCharacterId", None)) else None,
        },
        {
            "stage": 2,
            "name": "IDEA_INPUT",
            "label": STAGE_LABELS[2],
            "completed": current >= 2,
            "data": {"idea": getattr(p, "idea", None)} if getattr(p, "idea", None) else None,
        },
        {
            "stage": 3,
            "name": "IDEA_ENRICHMENT",
            "label": STAGE_LABELS[3],
            "completed": current >= 3,
            "data": enriched if enriched else None,
        },
        {
            "stage": 4,
            "name": "STORYBOARD",
            "label": STAGE_LABELS[4],
            "completed": current >= 4,
            "data": {"storyboard_id": storyboard_id} if storyboard_id else None,
        },
        {
            "stage": 5,
            "name": "VIDEO_GENERATION",
            "label": STAGE_LABELS[5],
            "completed": current >= 5,
            "data": None,
        },
    ]
    return stages


def project_to_item(p: object) -> dict:
    """프로젝트 DB 레코드 → dict 변환"""
    status = p.status
    ps = ProjectStatus(status) if status in ProjectStatus._value2member_map_ else None
    char_name, char_image = _get_character_info(p)
    stage = getattr(p, "currentStage", 1)
    return {
        "id": p.id,
        "title": p.title,
        "keyword": getattr(p, "keyword", ""),
        "current_stage": stage,
        "stage_name": STAGE_NAMES.get(stage, "UNKNOWN"),
        "character_id": p.characterId,
        "custom_character_id": getattr(p, "customCharacterId", None),
        "character_name": char_name,
        "character_image": char_image,
        "thumbnail_url": _get_thumbnail(p),
        "storyboard_id": getattr(p, "storyboardId", None),
        "idea": getattr(p, "idea", None),
        "enriched_idea": getattr(p, "enrichedIdea", None),
        "stages": _build_stages(p, char_name, char_image),
        "status": status,
        "status_label": STATUS_LABEL.get(ps, "알 수 없음") if ps else "알 수 없음",
        "progress": STATUS_PROGRESS.get(ps, 0) if ps else 0,
        "created_at": p.createdAt.isoformat(),
        "updated_at": p.updatedAt.isoformat() if hasattr(p, "updatedAt") else "",
    }
