from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def mock_db():
    """Prisma DB를 모킹"""
    mock_prisma = MagicMock()
    mock_prisma.is_connected.return_value = True
    mock_prisma.connect = AsyncMock()
    mock_prisma.disconnect = AsyncMock()

    mock_user = MagicMock()
    mock_user.find_unique = AsyncMock(return_value=None)
    mock_user.create = AsyncMock()
    mock_prisma.user = mock_user

    mock_refresh = MagicMock()
    mock_refresh.create = AsyncMock()
    mock_refresh.find_unique = AsyncMock(return_value=None)
    mock_refresh.delete = AsyncMock()
    mock_refresh.delete_many = AsyncMock()
    mock_prisma.refreshtoken = mock_refresh

    with (
        patch("app.core.database.db", mock_prisma),
        patch("app.services.auth.db", mock_prisma),
        patch("app.core.deps.db", mock_prisma),
    ):
        yield mock_prisma


@pytest.fixture
async def client(mock_db):
    """테스트용 AsyncClient"""
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
