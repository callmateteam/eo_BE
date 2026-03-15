"""트렌드 WebSocket 매니저 - 연결 관리 및 브로드캐스트"""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class TrendManager:
    """WebSocket 연결 관리 + 트렌드 데이터 브로드캐스트"""

    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._task: asyncio.Task | None = None

    async def connect(self, ws: WebSocket) -> None:
        """클라이언트 연결 수락"""
        await ws.accept()
        self._connections.add(ws)
        logger.info("WebSocket 연결: 총 %d명", len(self._connections))

    def disconnect(self, ws: WebSocket) -> None:
        """클라이언트 연결 해제"""
        self._connections.discard(ws)
        logger.info("WebSocket 해제: 총 %d명", len(self._connections))

    async def broadcast(self, data: dict) -> None:
        """모든 연결된 클라이언트에게 데이터 전송"""
        if not self._connections:
            return

        message = json.dumps(data, ensure_ascii=False)
        dead: list[WebSocket] = []

        for ws in self._connections:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)

        for ws in dead:
            self._connections.discard(ws)

    async def start_periodic_broadcast(self) -> None:
        """주기적으로 트렌드 데이터 브로드캐스트 (30초 간격)"""
        from app.services.creation_trend import get_creation_trends
        from app.services.trending import fetch_trending_keywords

        while True:
            try:
                if self._connections:
                    youtube_raw = await fetch_trending_keywords(max_results=5)
                    creation_raw = await get_creation_trends(limit=10)

                    await self.broadcast(
                        {
                            "youtube": youtube_raw,
                            "creation": creation_raw,
                        }
                    )
            except Exception:
                logger.exception("트렌드 브로드캐스트 실패")

            await asyncio.sleep(30)

    def start(self) -> None:
        """백그라운드 태스크 시작"""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self.start_periodic_broadcast())

    def stop(self) -> None:
        """백그라운드 태스크 중지"""
        if self._task and not self._task.done():
            self._task.cancel()


trend_manager = TrendManager()
