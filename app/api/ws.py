"""WebSocket 엔드포인트"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.trend_manager import trend_manager
from app.services.creation_trend import get_creation_trends
from app.services.trending import fetch_trending_keywords

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/ws/trends")
async def trends_websocket(ws: WebSocket) -> None:
    """트렌드 실시간 WebSocket

    연결 즉시 현재 트렌드 데이터를 전송하고,
    이후 30초 간격으로 업데이트를 push합니다.
    """
    await trend_manager.connect(ws)

    try:
        # 연결 즉시 현재 데이터 전송
        youtube_raw = await fetch_trending_keywords(max_results=5)
        creation_raw = await get_creation_trends(limit=10)

        await ws.send_text(
            json.dumps(
                {
                    "youtube": youtube_raw,
                    "creation": creation_raw,
                },
                ensure_ascii=False,
            )
        )

        # 연결 유지 (클라이언트 메시지 대기)
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        trend_manager.disconnect(ws)
    except Exception:
        logger.exception("WebSocket 오류")
        trend_manager.disconnect(ws)
