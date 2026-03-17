"""공유 httpx.AsyncClient — TCP 연결 재사용으로 지연 감소"""

from __future__ import annotations

import httpx

# OpenAI API 전용 (이미지/TTS/GPT 호출 공유)
_openai_client: httpx.AsyncClient | None = None

# 일반 다운로드/업로드 전용
_download_client: httpx.AsyncClient | None = None


def get_openai_client() -> httpx.AsyncClient:
    """OpenAI API 호출용 공유 클라이언트 (커넥션 풀 재사용)"""
    global _openai_client  # noqa: PLW0603
    if _openai_client is None or _openai_client.is_closed:
        _openai_client = httpx.AsyncClient(
            timeout=120,
            limits=httpx.Limits(
                max_connections=20,
                max_keepalive_connections=10,
            ),
        )
    return _openai_client


def get_download_client() -> httpx.AsyncClient:
    """파일 다운로드용 공유 클라이언트"""
    global _download_client  # noqa: PLW0603
    if _download_client is None or _download_client.is_closed:
        _download_client = httpx.AsyncClient(
            timeout=120,
            follow_redirects=True,
            limits=httpx.Limits(
                max_connections=10,
                max_keepalive_connections=5,
            ),
        )
    return _download_client


async def close_clients() -> None:
    """앱 종료 시 클라이언트 정리"""
    global _openai_client, _download_client  # noqa: PLW0603
    if _openai_client and not _openai_client.is_closed:
        await _openai_client.aclose()
        _openai_client = None
    if _download_client and not _download_client.is_closed:
        await _download_client.aclose()
        _download_client = None
