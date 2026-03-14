"""콘티(스토리보드) 관련 스키마"""

from __future__ import annotations

from pydantic import BaseModel, Field


class StoryboardCreateRequest(BaseModel):
    """콘티 생성 요청"""

    idea: str = Field(min_length=10, max_length=2000, description="영상 아이디어 (2-5줄)")
    character_id: str | None = Field(
        None, description="프리셋 캐릭터 ID (custom_character_id와 택 1)"
    )
    custom_character_id: str | None = Field(
        None, description="커스텀 캐릭터 ID (character_id와 택 1)"
    )


class StoryboardCreateResponse(BaseModel):
    """콘티 생성 응답"""

    id: str
    status: str = "GENERATING"
    message: str = "콘티 생성이 시작되었습니다."


class SceneItem(BaseModel):
    """콘티 장면 단건"""

    id: str
    scene_order: int
    title: str
    content: str
    image_prompt: str
    image_url: str | None = None
    image_status: str = "PENDING"
    duration: float


class StoryboardDetailResponse(BaseModel):
    """콘티 상세 조회 응답"""

    id: str
    idea: str
    character_id: str | None = None
    custom_character_id: str | None = None
    status: str
    error_msg: str | None = None
    scenes: list[SceneItem]
    total_duration: float
    created_at: str


class SceneUpdateRequest(BaseModel):
    """장면 내용 수정 요청"""

    title: str | None = Field(None, max_length=100, description="장면 제목")
    content: str | None = Field(None, max_length=2000, description="장면 내용")


class SceneImageRegenerateResponse(BaseModel):
    """이미지 재생성 응답"""

    scene_id: str
    status: str = "GENERATING"
    message: str = "이미지 재생성이 시작되었습니다."


class StoryboardListItem(BaseModel):
    """콘티 목록 항목"""

    id: str
    idea: str
    status: str
    scene_count: int
    total_duration: float
    created_at: str


class StoryboardListResponse(BaseModel):
    """콘티 목록 응답"""

    storyboards: list[StoryboardListItem]
    total: int
