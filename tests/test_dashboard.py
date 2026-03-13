from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.security import create_access_token
from app.core.timezone import KST

KST_NOW = datetime.now(KST)


STATUSES = ["CREATED", "SCRIPT_WRITTEN", "VOICE_GENERATED", "VIDEO_GENERATED", "COMPLETED"]


def _make_character(idx: int = 1):
    """테스트용 캐릭터 Mock 객체 생성"""
    c = MagicMock()
    c.id = f"char-uuid-{idx}"
    c.name = f"캐릭터{idx}"
    c.nameEn = f"Character{idx}"
    c.series = f"작품{idx}"
    c.category = "MEME"
    c.imageUrl = f"https://example.com/char{idx}.png"
    c.thumbnailUrl = f"https://example.com/char{idx}_thumb.png"
    c.description = f"캐릭터{idx} 설명"
    c.promptFeatures = f"character{idx} features"
    c.bodyType = "소년"
    c.primaryColor = "red"
    c.sortOrder = idx
    c.isActive = True
    return c


def _make_project(idx: int = 1):
    """테스트용 프로젝트 Mock 객체 생성"""
    char = _make_character(idx)
    p = MagicMock()
    p.id = f"project-uuid-{idx}"
    p.title = f"테스트 프로젝트 {idx}"
    p.characterId = char.id
    p.character = char
    p.status = STATUSES[(idx - 1) % len(STATUSES)]
    p.createdAt = KST_NOW - timedelta(days=idx)
    return p


def _make_user():
    """테스트용 유저 Mock 객체"""
    user = MagicMock()
    user.id = "user-uuid-123"
    user.username = "testuser"
    return user


@pytest.fixture
def auth_cookies():
    """유효한 JWT 토큰을 쿠키로"""
    token = create_access_token(subject="user-uuid-123")
    return {"access_token": token}


@pytest.fixture
def mock_dashboard_db():
    """대시보드 테스트용 DB 모킹"""
    mock_prisma = MagicMock()
    mock_prisma.is_connected.return_value = True
    mock_prisma.connect = AsyncMock()
    mock_prisma.disconnect = AsyncMock()

    mock_user = MagicMock()
    mock_user.find_unique = AsyncMock(return_value=_make_user())
    mock_prisma.user = mock_user

    mock_project = MagicMock()
    mock_project.find_many = AsyncMock(
        return_value=[_make_project(1), _make_project(2), _make_project(3)]
    )
    mock_prisma.project = mock_project

    mock_refresh = MagicMock()
    mock_refresh.create = AsyncMock()
    mock_refresh.find_unique = AsyncMock(return_value=None)
    mock_refresh.delete = AsyncMock()
    mock_prisma.refreshtoken = mock_refresh

    with (
        patch("app.core.database.db", mock_prisma),
        patch("app.services.auth.db", mock_prisma),
        patch("app.services.dashboard.db", mock_prisma),
        patch("app.core.deps.db", mock_prisma),
    ):
        yield mock_prisma


@pytest.fixture
async def authed_client(mock_dashboard_db):
    """인증된 테스트 클라이언트"""
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


class TestDashboard:
    """대시보드 API 테스트"""

    @pytest.mark.asyncio
    async def test_dashboard_success(self, authed_client, auth_cookies):
        """대시보드 정상 조회 - 프로젝트 목록 + 트렌드"""
        with patch(
            "app.api.dashboard.fetch_trending_keywords",
            new_callable=AsyncMock,
            return_value=[
                {"rank": 1, "keyword": "봄동 비빔밥", "traffic": "500+"},
                {"rank": 2, "keyword": "후안 소토", "traffic": "1000+"},
            ],
        ):
            resp = await authed_client.get("/api/dashboard", cookies=auth_cookies)

        assert resp.status_code == 200
        data = resp.json()
        assert "recent_projects" in data
        assert "trending_keywords" in data
        assert len(data["recent_projects"]) == 3
        assert len(data["trending_keywords"]) == 2

    @pytest.mark.asyncio
    async def test_dashboard_project_fields(self, authed_client, auth_cookies):
        """프로젝트 아이템에 필수 필드가 포함되는지 확인"""
        with patch(
            "app.api.dashboard.fetch_trending_keywords",
            new_callable=AsyncMock,
            return_value=[],
        ):
            resp = await authed_client.get("/api/dashboard", cookies=auth_cookies)

        project = resp.json()["recent_projects"][0]
        assert "id" in project
        assert "title" in project
        assert "character_id" in project
        assert "character_name" in project
        assert "character_image" in project
        assert "status" in project
        assert "status_label" in project
        assert "progress" in project
        assert "created_at" in project
        assert project["status"] == "CREATED"
        assert project["status_label"] == "프로젝트 생성"
        assert project["progress"] == 0

    @pytest.mark.asyncio
    async def test_dashboard_trend_fields(self, authed_client, auth_cookies):
        """트렌드 키워드에 필수 필드가 포함되는지 확인"""
        with patch(
            "app.api.dashboard.fetch_trending_keywords",
            new_callable=AsyncMock,
            return_value=[{"rank": 1, "keyword": "봄동 비빔밥", "traffic": "500+"}],
        ):
            resp = await authed_client.get("/api/dashboard", cookies=auth_cookies)

        trend = resp.json()["trending_keywords"][0]
        assert trend["rank"] == 1
        assert trend["keyword"] == "봄동 비빔밥"
        assert trend["traffic"] == "500+"

    @pytest.mark.asyncio
    async def test_dashboard_no_auth(self, authed_client):
        """인증 없이 대시보드 접근 시 401"""
        resp = await authed_client.get("/api/dashboard")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_dashboard_invalid_token(self, authed_client):
        """잘못된 토큰 쿠키로 대시보드 접근 시 401"""
        resp = await authed_client.get(
            "/api/dashboard",
            cookies={"access_token": "invalid-token-here"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_dashboard_expired_token(self, authed_client):
        """만료된 토큰 쿠키로 대시보드 접근 시 401"""
        expired_token = create_access_token(
            subject="user-uuid-123",
            expires_delta=timedelta(minutes=-1),
        )
        resp = await authed_client.get(
            "/api/dashboard",
            cookies={"access_token": expired_token},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_dashboard_empty_projects(self, authed_client, auth_cookies, mock_dashboard_db):
        """프로젝트가 없는 유저의 대시보드"""
        mock_dashboard_db.project.find_many = AsyncMock(return_value=[])

        with patch(
            "app.api.dashboard.fetch_trending_keywords",
            new_callable=AsyncMock,
            return_value=[],
        ):
            resp = await authed_client.get("/api/dashboard", cookies=auth_cookies)

        assert resp.status_code == 200
        assert resp.json()["recent_projects"] == []

    @pytest.mark.asyncio
    async def test_dashboard_project_progress_mapping(self, authed_client, auth_cookies):
        """각 상태별 진행률이 올바르게 매핑되는지 확인"""
        with patch(
            "app.api.dashboard.fetch_trending_keywords",
            new_callable=AsyncMock,
            return_value=[],
        ):
            resp = await authed_client.get("/api/dashboard", cookies=auth_cookies)

        projects = resp.json()["recent_projects"]
        # idx=1 → CREATED(0%), idx=2 → SCRIPT_WRITTEN(25%), idx=3 → VOICE_GENERATED(50%)
        assert projects[0]["progress"] == 0
        assert projects[1]["progress"] == 25
        assert projects[2]["progress"] == 50

    @pytest.mark.asyncio
    async def test_dashboard_trend_api_failure(self, authed_client, auth_cookies):
        """트렌드 API 실패 시에도 대시보드는 정상 응답 (트렌드만 빈 배열)"""
        with patch(
            "app.api.dashboard.fetch_trending_keywords",
            new_callable=AsyncMock,
            return_value=[],
        ):
            resp = await authed_client.get("/api/dashboard", cookies=auth_cookies)

        assert resp.status_code == 200
        assert resp.json()["trending_keywords"] == []


class TestTrendingService:
    """Google Trends 서비스 유닛 테스트"""

    @pytest.mark.asyncio
    async def test_fetch_with_cache(self):
        """캐시가 유효하면 API 호출 없이 캐시 반환"""
        import time

        from app.services.trending import _trend_cache, fetch_trending_keywords

        cached_data = [
            {"rank": 1, "keyword": "캐시키워드", "traffic": "500+"},
            {"rank": 2, "keyword": "테스트", "traffic": "200+"},
        ]
        _trend_cache["data"] = cached_data
        _trend_cache["expires_at"] = time.time() + 600

        result = await fetch_trending_keywords(max_results=10)
        assert len(result) == 2
        assert result[0]["keyword"] == "캐시키워드"

        _trend_cache["data"] = None
        _trend_cache["expires_at"] = 0.0

    @pytest.mark.asyncio
    async def test_fetch_respects_max_results(self):
        """max_results로 결과 수 제한"""
        import time

        from app.services.trending import _trend_cache, fetch_trending_keywords

        cached_data = [
            {"rank": i, "keyword": f"키워드{i}", "traffic": f"{100 * i}+"} for i in range(1, 11)
        ]
        _trend_cache["data"] = cached_data
        _trend_cache["expires_at"] = time.time() + 600

        result = await fetch_trending_keywords(max_results=5)
        assert len(result) == 5

        _trend_cache["data"] = None
        _trend_cache["expires_at"] = 0.0

    @pytest.mark.asyncio
    async def test_fetch_api_failure_returns_empty(self):
        """Google Trends API 실패 시 빈 리스트 반환"""
        from app.services.trending import _trend_cache, fetch_trending_keywords

        _trend_cache["data"] = None
        _trend_cache["expires_at"] = 0.0

        with patch("app.services.trending.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(side_effect=Exception("Network error"))
            mock_client_cls.return_value = mock_client

            result = await fetch_trending_keywords()
            assert result == []
