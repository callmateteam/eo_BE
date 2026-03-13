from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient


def _make_character(idx: int = 1, category: str = "MEME"):
    """테스트용 캐릭터 Mock 객체"""
    c = MagicMock()
    c.id = f"char-uuid-{idx}"
    c.name = f"캐릭터{idx}"
    c.nameEn = f"Character{idx}"
    c.series = f"작품{idx}"
    c.category = category
    c.imageUrl = f"https://example.com/char{idx}.png"
    c.thumbnailUrl = f"https://example.com/char{idx}_thumb.png"
    c.description = f"캐릭터{idx} 외형 설명"
    c.promptFeatures = f"character{idx} features for AI prompt"
    c.bodyType = "소년"
    c.primaryColor = "red"
    c.sortOrder = idx
    c.isActive = True
    return c


@pytest.fixture
def mock_char_db():
    """캐릭터 테스트용 DB 모킹"""
    mock_prisma = MagicMock()
    mock_prisma.is_connected.return_value = True
    mock_prisma.connect = AsyncMock()
    mock_prisma.disconnect = AsyncMock()

    mock_character = MagicMock()
    mock_character.find_many = AsyncMock(
        return_value=[_make_character(1), _make_character(2), _make_character(3)]
    )
    mock_character.find_unique = AsyncMock(return_value=_make_character(1))
    mock_character.count = AsyncMock(return_value=3)
    mock_prisma.character = mock_character

    with (
        patch("app.core.database.db", mock_prisma),
        patch("app.services.character.db", mock_prisma),
    ):
        yield mock_prisma


@pytest.fixture
async def char_client(mock_char_db):
    """캐릭터 테스트 클라이언트"""
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


class TestCharacterList:
    """캐릭터 목록 API 테스트"""

    @pytest.mark.asyncio
    async def test_list_all_characters(self, char_client):
        """전체 캐릭터 목록 조회"""
        resp = await char_client.get("/api/characters")
        assert resp.status_code == 200
        data = resp.json()
        assert "characters" in data
        assert "total" in data
        assert data["total"] == 3
        assert len(data["characters"]) == 3

    @pytest.mark.asyncio
    async def test_character_fields(self, char_client):
        """캐릭터 필수 필드 확인"""
        resp = await char_client.get("/api/characters")
        char = resp.json()["characters"][0]
        assert "id" in char
        assert "name" in char
        assert "name_en" in char
        assert "series" in char
        assert "category" in char
        assert "category_label" in char
        assert "image_url" in char
        assert "thumbnail_url" in char
        assert "description" in char
        assert "prompt_features" in char
        assert "body_type" in char
        assert "primary_color" in char

    @pytest.mark.asyncio
    async def test_character_category_label(self, char_client):
        """카테고리 라벨이 한글로 표시되는지 확인"""
        resp = await char_client.get("/api/characters")
        char = resp.json()["characters"][0]
        assert char["category"] == "MEME"
        assert "밈" in char["category_label"]


class TestCharacterByCategory:
    """카테고리별 캐릭터 조회 테스트"""

    @pytest.mark.asyncio
    async def test_filter_by_category(self, char_client, mock_char_db):
        """카테고리별 필터링"""
        action_chars = [_make_character(1, "ACTION"), _make_character(2, "ACTION")]
        mock_char_db.character.find_many = AsyncMock(return_value=action_chars)

        resp = await char_client.get("/api/characters/category/ACTION")
        assert resp.status_code == 200
        data = resp.json()
        assert data["category"] == "ACTION"
        assert "액션" in data["category_label"]
        assert len(data["characters"]) == 2

    @pytest.mark.asyncio
    async def test_invalid_category(self, char_client):
        """잘못된 카테고리"""
        resp = await char_client.get("/api/characters/category/INVALID")
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_empty_category(self, char_client, mock_char_db):
        """빈 카테고리"""
        mock_char_db.character.find_many = AsyncMock(return_value=[])
        resp = await char_client.get("/api/characters/category/CUTE")
        assert resp.status_code == 200
        assert resp.json()["characters"] == []


class TestCharacterDetail:
    """캐릭터 단건 조회 테스트"""

    @pytest.mark.asyncio
    async def test_get_character(self, char_client):
        """캐릭터 단건 조회"""
        resp = await char_client.get("/api/characters/char-uuid-1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "char-uuid-1"
        assert data["name"] == "캐릭터1"
        assert data["prompt_features"] == "character1 features for AI prompt"

    @pytest.mark.asyncio
    async def test_get_character_not_found(self, char_client, mock_char_db):
        """존재하지 않는 캐릭터"""
        mock_char_db.character.find_unique = AsyncMock(return_value=None)
        resp = await char_client.get("/api/characters/nonexistent-id")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_get_inactive_character(self, char_client, mock_char_db):
        """비활성 캐릭터는 404"""
        inactive = _make_character(1)
        inactive.isActive = False
        mock_char_db.character.find_unique = AsyncMock(return_value=inactive)
        resp = await char_client.get("/api/characters/char-uuid-1")
        assert resp.status_code == 404
