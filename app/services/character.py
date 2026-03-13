from __future__ import annotations

from app.core.database import db
from app.schemas.character import CATEGORY_LABEL, CharacterCategory


async def get_all_characters() -> list[dict]:
    """활성화된 전체 캐릭터 목록 조회 (정렬순)"""
    characters = await db.character.find_many(
        where={"isActive": True},
        order={"sortOrder": "asc"},
    )
    return [_to_dict(c) for c in characters]


async def get_characters_by_category(category: str) -> list[dict]:
    """카테고리별 캐릭터 목록 조회"""
    characters = await db.character.find_many(
        where={"category": category, "isActive": True},
        order={"sortOrder": "asc"},
    )
    return [_to_dict(c) for c in characters]


async def get_character_by_id(character_id: str) -> dict | None:
    """캐릭터 단건 조회"""
    c = await db.character.find_unique(where={"id": character_id})
    if not c or not c.isActive:
        return None
    return _to_dict(c)


def _to_dict(c: object) -> dict:
    """캐릭터 모델을 응답 dict로 변환"""
    category = CharacterCategory(c.category)
    return {
        "id": c.id,
        "name": c.name,
        "name_en": c.nameEn,
        "series": c.series,
        "category": c.category,
        "category_label": CATEGORY_LABEL.get(category, ""),
        "image_url": c.imageUrl,
        "thumbnail_url": c.thumbnailUrl,
        "description": c.description,
        "prompt_features": c.promptFeatures,
        "height_cm": c.heightCm,
        "body_build": c.bodyBuild,
        "face_features": c.faceFeatures,
        "costume_desc": c.costumeDesc,
        "distinct_marks": c.distinctMarks,
        "veo_prompt": c.veoPrompt,
        "body_type": c.bodyType,
        "primary_color": c.primaryColor,
    }
