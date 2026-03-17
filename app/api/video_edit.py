"""영상 편집 API 라우터"""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, WebSocket
from starlette.websockets import WebSocketDisconnect

from app.core.deps import get_current_user, get_ws_user_id
from app.schemas.auth import ErrorResponse
from app.schemas.video_edit import (
    EditData,
    RenderStartResponse,
    ThumbnailRequest,
    ThumbnailResponse,
    TtsCreateRequest,
    TtsCreateResponse,
    UndoResponse,
    VideoEditResponse,
    VideoEditUpdateRequest,
)
from app.services.tts import generate_tts
from app.services.video_edit import get_or_create_edit, undo_edit, update_edit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/storyboards", tags=["video-edit"])

# 렌더링 진행률 브로드캐스트용
_render_subs: dict[str, set[WebSocket]] = {}
_background_tasks: set[asyncio.Task] = set()  # type: ignore[type-arg]


@router.get(
    "/{storyboard_id}/edit",
    response_model=VideoEditResponse,
    summary="편집 상태 조회",
    responses={
        401: {"model": ErrorResponse, "description": "인증 필요"},
        404: {"model": ErrorResponse, "description": "스토리보드 없음"},
    },
)
async def get_edit(
    storyboard_id: str,
    current_user: dict = Depends(get_current_user),
) -> VideoEditResponse:
    """편집 상태 조회 (없으면 스토리보드 기반 초기값 자동 생성)"""
    result = await get_or_create_edit(storyboard_id, current_user["id"])
    if not result:
        raise HTTPException(status_code=404, detail="스토리보드를 찾을 수 없습니다")
    return VideoEditResponse(**result)


@router.patch(
    "/{storyboard_id}/edit",
    response_model=VideoEditResponse,
    summary="편집 저장 (히스토리 자동 생성)",
    responses={
        401: {"model": ErrorResponse, "description": "인증 필요"},
        404: {"model": ErrorResponse, "description": "스토리보드 없음"},
    },
)
async def save_edit(
    storyboard_id: str,
    req: VideoEditUpdateRequest,
    current_user: dict = Depends(get_current_user),
) -> VideoEditResponse:
    """편집 저장 — version 증가 + 이전 상태 히스토리 자동 저장"""
    result = await update_edit(storyboard_id, current_user["id"], req.edit_data)
    if not result:
        raise HTTPException(status_code=404, detail="스토리보드를 찾을 수 없습니다")
    return VideoEditResponse(**result)


@router.post(
    "/{storyboard_id}/edit/undo",
    response_model=UndoResponse,
    summary="편집 되돌리기 (Undo)",
    responses={
        401: {"model": ErrorResponse, "description": "인증 필요"},
        404: {"model": ErrorResponse, "description": "스토리보드 없음"},
        409: {"model": ErrorResponse, "description": "되돌릴 히스토리 없음"},
    },
)
async def undo(
    storyboard_id: str,
    current_user: dict = Depends(get_current_user),
) -> UndoResponse:
    """한 단계 되돌리기 (최대 50단계)"""
    result = await undo_edit(storyboard_id, current_user["id"])
    if not result:
        raise HTTPException(status_code=409, detail="더 이상 되돌릴 수 없습니다")
    return UndoResponse(
        id=result["id"],
        version=result["version"],
        edit_data=EditData(**result["edit_data"]),
    )


@router.post(
    "/{storyboard_id}/edit/tts",
    response_model=TtsCreateResponse,
    summary="커스텀 TTS 생성",
    responses={
        401: {"model": ErrorResponse, "description": "인증 필요"},
        500: {"model": ErrorResponse, "description": "TTS 생성 실패"},
    },
)
async def create_tts(
    storyboard_id: str,
    req: TtsCreateRequest,
    current_user: dict = Depends(get_current_user),
) -> TtsCreateResponse:
    """사용자 입력 텍스트로 TTS 생성 → audio_url 반환"""
    try:
        audio_url = await generate_tts(
            text=req.text,
            voice_id=req.voice_id,
            voice_style=req.voice_style,
            user_id=current_user["id"],
        )
    except Exception as exc:
        logger.exception("커스텀 TTS 생성 실패")
        raise HTTPException(status_code=500, detail=f"TTS 생성 실패: {exc}") from None

    return TtsCreateResponse(audio_url=audio_url)


@router.post(
    "/{storyboard_id}/thumbnail",
    response_model=ThumbnailResponse,
    summary="썸네일 프레임 추출",
    responses={
        401: {"model": ErrorResponse, "description": "인증 필요"},
        404: {"model": ErrorResponse, "description": "스토리보드 없음"},
        500: {"model": ErrorResponse, "description": "썸네일 추출 실패"},
    },
)
async def extract_thumbnail(
    storyboard_id: str,
    req: ThumbnailRequest,
    current_user: dict = Depends(get_current_user),
) -> ThumbnailResponse:
    """영상 내 특정 시간의 프레임을 썸네일로 추출"""
    from app.core.database import db
    from app.services.video_edit_render import extract_thumbnail_frame

    sb = await db.storyboard.find_first(
        where={"id": storyboard_id, "userId": current_user["id"]},
    )
    if not sb or not sb.finalVideoUrl:
        raise HTTPException(status_code=404, detail="완성된 영상이 없습니다")

    try:
        url = await extract_thumbnail_frame(
            video_url=sb.finalVideoUrl,
            time_seconds=req.time,
            user_id=current_user["id"],
        )
    except Exception as exc:
        logger.exception("썸네일 추출 실패")
        raise HTTPException(status_code=500, detail=str(exc)) from None

    # heroFrameUrl 업데이트
    await db.storyboard.update(
        where={"id": storyboard_id},
        data={"heroFrameUrl": url},
    )

    return ThumbnailResponse(thumbnail_url=url)


@router.post(
    "/{storyboard_id}/render",
    response_model=RenderStartResponse,
    status_code=202,
    summary="편집 적용 최종 렌더링",
    responses={
        401: {"model": ErrorResponse, "description": "인증 필요"},
        404: {"model": ErrorResponse, "description": "편집 데이터 없음"},
    },
)
async def start_render(
    storyboard_id: str,
    current_user: dict = Depends(get_current_user),
) -> RenderStartResponse:
    """editData 기반 최종 영상 렌더링 시작 (백그라운드)

    진행률은 WS `/api/storyboards/ws/{id}/render`로 확인 가능
    """
    from app.services.video_edit_render import render_with_edits

    edit = await get_or_create_edit(storyboard_id, current_user["id"])
    if not edit:
        raise HTTPException(status_code=404, detail="편집 데이터를 찾을 수 없습니다")

    render_key = f"{storyboard_id}:render"

    async def render_callback(msg: dict) -> None:
        subs = _render_subs.get(render_key, set())
        if not subs:
            return
        is_terminal = msg.get("status") in ("RENDER_READY", "FAILED")
        text = json.dumps(msg, ensure_ascii=False)
        dead: list[WebSocket] = []
        for ws in subs:
            try:
                await ws.send_text(text)
                if is_terminal:
                    await ws.close()
            except Exception:
                dead.append(ws)
        if is_terminal:
            _render_subs.pop(render_key, None)
        else:
            for ws in dead:
                subs.discard(ws)

    task = asyncio.create_task(
        render_with_edits(
            storyboard_id=storyboard_id,
            user_id=current_user["id"],
            edit_data=EditData(**edit["edit_data"]),
            progress_callback=render_callback,
        )
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    return RenderStartResponse(storyboard_id=storyboard_id)


# ── WebSocket: 렌더링 진행률 ──


@router.websocket("/ws/{storyboard_id}/render")
async def render_progress_ws(ws: WebSocket, storyboard_id: str) -> None:
    """렌더링 진행률 WebSocket"""
    await ws.accept()

    user_id = await get_ws_user_id(ws)
    if not user_id:
        await ws.send_text(json.dumps({"error": "인증이 필요합니다"}))
        await ws.close(code=4001)
        return

    # 초기 상태 전송
    await ws.send_text(
        json.dumps(
            {
                "storyboard_id": storyboard_id,
                "status": "RENDERING",
                "progress": 0,
                "step": "렌더링 대기 중...",
            },
            ensure_ascii=False,
        )
    )

    render_key = f"{storyboard_id}:render"
    if render_key not in _render_subs:
        _render_subs[render_key] = set()
    _render_subs[render_key].add(ws)

    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        _render_subs.get(render_key, set()).discard(ws)
        if render_key in _render_subs and not _render_subs[render_key]:
            del _render_subs[render_key]
