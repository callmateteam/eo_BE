"""커스텀 캐릭터 API 라우터 + WebSocket 진행률"""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, WebSocket
from jose import JWTError, jwt
from starlette.websockets import WebSocketDisconnect

from app.core.config import settings
from app.core.database import db
from app.core.deps import get_current_user
from app.core.security import ACCESS_TOKEN_COOKIE, ALGORITHM
from app.schemas.auth import ErrorResponse
from app.schemas.custom_character import (
    CharacterStyle,
    CustomCharacterCreateResponse,
    CustomCharacterItem,
    CustomCharacterListResponse,
    VoiceId,
)
from app.services.custom_character import (
    get_custom_character_by_id,
    get_custom_characters,
    process_custom_character,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/characters/custom", tags=["custom-characters"])

# 진행률 브로드캐스트용 (character_id → set of WebSocket)
_progress_subs: dict[str, set[WebSocket]] = {}
# asyncio.create_task GC 수거 방지용
_background_tasks: set[asyncio.Task] = set()  # type: ignore[type-arg]

ALLOWED_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/webp"}
MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10MB


@router.post(
    "",
    response_model=CustomCharacterCreateResponse,
    status_code=201,
    summary="커스텀 캐릭터 생성",
    responses={
        401: {"model": ErrorResponse, "description": "인증 필요"},
        400: {"model": ErrorResponse, "description": "이미지 형식/크기 오류"},
        422: {"model": ErrorResponse, "description": "요청 파라미터 유효성 검사 실패"},
    },
)
async def create_custom_character(
    name: str = Form(min_length=1, max_length=50, description="캐릭터 이름"),
    description: str = Form(min_length=1, max_length=500, description="캐릭터 설명"),
    style: CharacterStyle = Form(description="렌더링 스타일"),
    voice_id: VoiceId = Form(default=VoiceId.ALLOY, description="TTS 음성"),
    image1: UploadFile = File(description="캐릭터 이미지 1"),
    image2: UploadFile = File(description="캐릭터 이미지 2"),
    current_user: dict = Depends(get_current_user),
) -> CustomCharacterCreateResponse:
    """커스텀 캐릭터 생성 시작

    이미지 2장 + 이름 + 설명 + 스타일을 받아 백그라운드에서 처리합니다.
    GPT-4o Vision이 이미지를 분석하여 최적화된 프롬프트를 자동 생성합니다.
    진행률은 WebSocket(/ws/custom-character/{id})으로 실시간 확인 가능합니다.
    """
    # 이미지 검증
    for img, label in [(image1, "image1"), (image2, "image2")]:
        if img.content_type not in ALLOWED_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"{label}: 이미지만 업로드 가능합니다 (PNG, JPG, WebP)",
            )

    data1 = await image1.read()
    data2 = await image2.read()

    for data, label in [(data1, "image1"), (data2, "image2")]:
        if len(data) > MAX_IMAGE_SIZE:
            raise HTTPException(
                status_code=400,
                detail=f"{label}: 이미지 크기는 10MB 이하여야 합니다",
            )

    # DB에 PROCESSING 상태로 먼저 생성
    record = await db.customcharacter.create(
        data={
            "name": name,
            "description": description,
            "style": style.value,
            "voiceId": voice_id.value,
            "imageUrl1": "",
            "imageUrl2": "",
            "userId": current_user["id"],
        }
    )

    # 백그라운드 태스크 시작
    async def progress_callback(pct: int, step: str) -> None:
        """WebSocket 구독자에게 진행률 전송, 완료/실패 시 연결 종료"""
        subs = _progress_subs.get(record.id, set())
        if not subs:
            return
        is_terminal = pct >= 100 or pct < 0
        msg = json.dumps(
            {
                "character_id": record.id,
                "progress": max(pct, 0),
                "step": step,
                "status": "FAILED" if pct < 0 else ("COMPLETED" if pct >= 100 else "PROCESSING"),
            },
            ensure_ascii=False,
        )
        dead: list[WebSocket] = []
        for ws in subs:
            try:
                await ws.send_text(msg)
                if is_terminal:
                    await ws.close()
            except Exception:
                dead.append(ws)
        if is_terminal:
            _progress_subs.pop(record.id, None)
        else:
            for ws in dead:
                subs.discard(ws)

    task = asyncio.create_task(
        process_custom_character(
            character_id=record.id,
            user_id=current_user["id"],
            name=name,
            description=description,
            style=style.value,
            image_data_1=data1,
            image_data_2=data2,
            content_type_1=image1.content_type or "image/png",
            content_type_2=image2.content_type or "image/png",
            progress_callback=progress_callback,
        )
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    return CustomCharacterCreateResponse(id=record.id)


@router.get(
    "",
    response_model=CustomCharacterListResponse,
    summary="내 커스텀 캐릭터 목록",
    responses={
        401: {"model": ErrorResponse, "description": "인증 필요"},
    },
)
async def list_custom_characters(
    current_user: dict = Depends(get_current_user),
) -> CustomCharacterListResponse:
    """내가 만든 커스텀 캐릭터 목록 조회"""
    chars = await get_custom_characters(current_user["id"])
    items = [CustomCharacterItem(**c) for c in chars]
    return CustomCharacterListResponse(characters=items, total=len(items))


@router.get(
    "/{character_id}",
    response_model=CustomCharacterItem,
    summary="커스텀 캐릭터 단건 조회",
    responses={
        401: {"model": ErrorResponse, "description": "인증 필요"},
        404: {"model": ErrorResponse, "description": "캐릭터를 찾을 수 없음"},
    },
)
async def get_custom_character(
    character_id: str,
    current_user: dict = Depends(get_current_user),
) -> CustomCharacterItem:
    """커스텀 캐릭터 단건 조회 (본인 소유만)"""
    char = await get_custom_character_by_id(character_id, current_user["id"])
    if not char:
        raise HTTPException(status_code=404, detail="캐릭터를 찾을 수 없습니다")
    return CustomCharacterItem(**char)


@router.delete(
    "/{character_id}",
    status_code=204,
    summary="커스텀 캐릭터 삭제",
    responses={
        401: {"model": ErrorResponse, "description": "인증 필요"},
        404: {"model": ErrorResponse, "description": "캐릭터를 찾을 수 없음"},
        409: {
            "model": ErrorResponse,
            "description": "사용 중인 캐릭터 (스토리보드 연결)",
        },
    },
)
async def delete_custom_character(
    character_id: str,
    current_user: dict = Depends(get_current_user),
) -> None:
    """커스텀 캐릭터 삭제 (본인 소유만)

    스토리보드에서 사용 중인 캐릭터는 삭제할 수 없습니다.
    """
    record = await db.customcharacter.find_first(
        where={"id": character_id, "userId": current_user["id"]},
    )
    if not record:
        raise HTTPException(
            status_code=404, detail="캐릭터를 찾을 수 없습니다"
        )

    # 사용 중인 스토리보드 확인
    linked = await db.storyboard.count(
        where={"customCharacterId": character_id}
    )
    if linked > 0:
        raise HTTPException(
            status_code=409,
            detail="이 캐릭터를 사용하는 콘티가 있어 삭제할 수 없습니다",
        )

    await db.customcharacter.delete(where={"id": character_id})


# ── WebSocket: 캐릭터 생성 진행률 ──


@router.websocket("/ws/{character_id}")
async def custom_character_progress_ws(ws: WebSocket, character_id: str) -> None:
    """커스텀 캐릭터 생성 진행률 WebSocket

    연결 즉시 현재 상태 전송, 이후 실시간 진행률 업데이트.
    """
    await ws.accept()

    # 쿠키 기반 인증
    token = ws.cookies.get(ACCESS_TOKEN_COOKIE)
    user_id: str | None = None
    if token:
        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
            user_id = payload.get("sub")
        except JWTError:
            pass
    if not user_id:
        await ws.send_text(json.dumps({"error": "인증이 필요합니다"}))
        await ws.close(code=4001)
        return

    # 소유권 확인
    record = await db.customcharacter.find_first(where={"id": character_id, "userId": user_id})
    if not record:
        await ws.send_text(json.dumps({"error": "캐릭터를 찾을 수 없습니다"}))
        await ws.close(code=4004)
        return

    status = record.status
    progress = 100 if status == "COMPLETED" else (0 if status == "PROCESSING" else -1)
    await ws.send_text(
        json.dumps(
            {
                "character_id": character_id,
                "progress": max(progress, 0),
                "step": (
                    "완료"
                    if status == "COMPLETED"
                    else ("처리 중" if status == "PROCESSING" else "실패")
                ),
                "status": status,
            },
            ensure_ascii=False,
        )
    )

    if status != "PROCESSING":
        await ws.close()
        return

    # 구독 등록
    if character_id not in _progress_subs:
        _progress_subs[character_id] = set()
    _progress_subs[character_id].add(ws)

    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        _progress_subs.get(character_id, set()).discard(ws)
        if character_id in _progress_subs and not _progress_subs[character_id]:
            del _progress_subs[character_id]
