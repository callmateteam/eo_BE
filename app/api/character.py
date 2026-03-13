from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.schemas.auth import ErrorResponse
from app.schemas.character import (
    CATEGORY_LABEL,
    CharacterCategory,
    CharacterItem,
    CharacterListResponse,
    CharactersByCategoryResponse,
)
from app.services.character import (
    get_all_characters,
    get_character_by_id,
    get_characters_by_category,
)

router = APIRouter(prefix="/characters", tags=["characters"])


@router.get(
    "",
    response_model=CharacterListResponse,
    summary="전체 캐릭터 목록",
)
async def list_characters():
    """전체 캐릭터 목록을 정렬 순서대로 조회합니다."""
    chars = await get_all_characters()
    items = [CharacterItem(**c) for c in chars]
    return CharacterListResponse(characters=items, total=len(items))


@router.get(
    "/category/{category}",
    response_model=CharactersByCategoryResponse,
    summary="카테고리별 캐릭터 목록",
    responses={
        422: {
            "model": ErrorResponse,
            "description": "유효하지 않은 카테고리 (MEME, ACTION, CUTE, BEAUTY 중 하나)",
        },
    },
)
async def list_characters_by_category(category: CharacterCategory):
    """지정한 카테고리에 속하는 캐릭터 목록을 조회합니다.

    카테고리: MEME, ACTION, CUTE, BEAUTY
    """
    chars = await get_characters_by_category(category.value)
    items = [CharacterItem(**c) for c in chars]
    return CharactersByCategoryResponse(
        category=category,
        category_label=CATEGORY_LABEL.get(category, ""),
        characters=items,
    )


@router.get(
    "/{character_id}",
    response_model=CharacterItem,
    summary="캐릭터 단건 조회",
    responses={
        404: {"model": ErrorResponse, "description": "캐릭터를 찾을 수 없음"},
    },
)
async def get_character(character_id: str):
    """캐릭터 UUID로 단건 조회합니다."""
    char = await get_character_by_id(character_id)
    if not char:
        raise HTTPException(status_code=404, detail="캐릭터를 찾을 수 없습니다.")
    return CharacterItem(**char)
