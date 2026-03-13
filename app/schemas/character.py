from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class CharacterCategory(str, Enum):  # noqa: UP042
    """캐릭터 카테고리"""

    MEME = "MEME"
    ACTION = "ACTION"
    CUTE = "CUTE"
    BEAUTY = "BEAUTY"


CATEGORY_LABEL: dict[CharacterCategory, str] = {
    CharacterCategory.MEME: "밈 / 표정 캐릭터",
    CharacterCategory.ACTION: "액션 캐릭터",
    CharacterCategory.CUTE: "귀여운 캐릭터",
    CharacterCategory.BEAUTY: "인기 미남/미소녀",
}


class CharacterItem(BaseModel):
    """캐릭터 응답 아이템"""

    id: str
    name: str
    name_en: str
    series: str
    category: CharacterCategory
    category_label: str
    image_url: str
    thumbnail_url: str
    description: str
    prompt_features: str
    height_cm: int
    body_build: str
    face_features: str
    costume_desc: str
    distinct_marks: str
    veo_prompt: str
    body_type: str
    primary_color: str


class CharacterListResponse(BaseModel):
    """캐릭터 목록 응답"""

    characters: list[CharacterItem]
    total: int


class CharactersByCategoryResponse(BaseModel):
    """카테고리별 캐릭터 응답"""

    category: CharacterCategory
    category_label: str
    characters: list[CharacterItem]
