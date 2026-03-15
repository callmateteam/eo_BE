"""커스텀 캐릭터 관련 스키마"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class CharacterStyle(str, Enum):  # noqa: UP042
    """캐릭터 렌더링 스타일"""

    REALISTIC = "REALISTIC"
    ANIME = "ANIME"
    CARTOON_3D = "CARTOON_3D"
    ILLUSTRATION_2D = "ILLUSTRATION_2D"
    CLAY = "CLAY"
    WATERCOLOR = "WATERCOLOR"


STYLE_LABEL: dict[CharacterStyle, str] = {
    CharacterStyle.REALISTIC: "실사",
    CharacterStyle.ANIME: "애니메이션",
    CharacterStyle.CARTOON_3D: "3D 카툰",
    CharacterStyle.ILLUSTRATION_2D: "2D 일러스트",
    CharacterStyle.CLAY: "클레이",
    CharacterStyle.WATERCOLOR: "수채화",
}

STYLE_PROMPT: dict[CharacterStyle, str] = {
    CharacterStyle.REALISTIC: "photorealistic live action style",
    CharacterStyle.ANIME: "anime-inspired live action style",
    CharacterStyle.CARTOON_3D: "3D cartoon Pixar-style CGI",
    CharacterStyle.ILLUSTRATION_2D: "2D flat illustration style",
    CharacterStyle.CLAY: "claymation stop-motion style",
    CharacterStyle.WATERCOLOR: "watercolor painting style",
}


class VoiceId(str, Enum):  # noqa: UP042
    """OpenAI TTS 음성 선택지"""

    ALLOY = "alloy"
    ASH = "ash"
    BALLAD = "ballad"
    CORAL = "coral"
    ECHO = "echo"
    FABLE = "fable"
    ONYX = "onyx"
    NOVA = "nova"
    SAGE = "sage"
    SHIMMER = "shimmer"


class CustomCharacterCreateResponse(BaseModel):
    """커스텀 캐릭터 생성 응답"""

    id: str
    status: str = "PROCESSING"
    message: str = "캐릭터 생성이 시작되었습니다."


class CustomCharacterItem(BaseModel):
    """커스텀 캐릭터 조회 응답"""

    id: str
    name: str
    description: str
    style: CharacterStyle
    style_label: str
    image_url_1: str
    image_url_2: str
    veo_prompt: str | None = None
    voice_id: str = "alloy"
    voice_style: str = ""
    status: str
    error_msg: str | None = None
    created_at: str


class CustomCharacterListResponse(BaseModel):
    """커스텀 캐릭터 목록 응답"""

    characters: list[CustomCharacterItem]
    total: int


class CustomCharacterProgress(BaseModel):
    """WebSocket 진행률 메시지"""

    character_id: str
    progress: int = Field(ge=0, le=100)
    step: str
    status: str = "PROCESSING"
    error: str | None = None
