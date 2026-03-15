"""콘티(스토리보드) API 라우터 + WebSocket 진행률"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable

from fastapi import APIRouter, Depends, HTTPException, WebSocket
from jose import JWTError, jwt
from starlette.websockets import WebSocketDisconnect

from app.core.config import settings
from app.core.database import db
from app.core.deps import get_current_user
from app.core.security import ACCESS_TOKEN_COOKIE, ALGORITHM
from app.schemas.auth import ErrorResponse
from app.schemas.storyboard import (
    SceneImageRegenerateResponse,
    SceneItem,
    SceneUpdateRequest,
    StoryboardCreateRequest,
    StoryboardCreateResponse,
    StoryboardDetailResponse,
    StoryboardListItem,
    StoryboardListResponse,
    VideoGenerationStartResponse,
)
from app.services.storyboard import (
    get_character_info,
    process_storyboard,
    regenerate_scene_image_task,
)
from app.services.video_generation import process_storyboard_videos

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/storyboards", tags=["storyboards"])

# 진행률 브로드캐스트용
_progress_subs: dict[str, set[WebSocket]] = {}
_background_tasks: set[asyncio.Task] = set()  # type: ignore[type-arg]

# 유저별 동시 생성 제한
_MAX_CONCURRENT_PER_USER = 3


async def _authenticate_ws(ws: WebSocket) -> str | None:
    """WebSocket 쿠키에서 유저 ID 추출 (인증 실패 시 None)"""
    token = ws.cookies.get(ACCESS_TOKEN_COOKIE)
    if not token:
        return None
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        return payload.get("sub")
    except JWTError:
        return None


def _make_progress_callback(
    entity_id: str,
) -> Callable[[int, str], Awaitable[None]]:
    """WebSocket 진행률 콜백 생성"""

    async def callback(pct: int, step: str) -> None:
        subs = _progress_subs.get(entity_id, set())
        if not subs:
            return
        is_terminal = pct >= 100 or pct < 0
        msg = json.dumps(
            {
                "id": entity_id,
                "progress": max(pct, 0),
                "step": step,
                "status": ("FAILED" if pct < 0 else ("COMPLETED" if pct >= 100 else "PROCESSING")),
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
            _progress_subs.pop(entity_id, None)
        else:
            for ws in dead:
                subs.discard(ws)

    return callback


# ── REST 엔드포인트 ──


@router.post(
    "",
    response_model=StoryboardCreateResponse,
    status_code=201,
    summary="콘티 생성",
    responses={
        400: {"model": ErrorResponse, "description": "캐릭터 선택 오류"},
        401: {"model": ErrorResponse, "description": "인증 필요"},
        422: {
            "model": ErrorResponse,
            "description": "요청 파라미터 유효성 검사 실패",
        },
        429: {
            "model": ErrorResponse,
            "description": "동시 생성 제한 초과",
        },
    },
)
async def create_storyboard(
    req: StoryboardCreateRequest,
    current_user: dict = Depends(get_current_user),
) -> StoryboardCreateResponse:
    """콘티 생성 시작

    캐릭터 + 아이디어를 받아 GPT-4o-mini로 장면을 분할하고,
    GPT 이미지(gpt-image-1)로 각 장면의 시작 프레임을 생성합니다.
    생성된 이미지는 콘티 썸네일 겸 Kling AI 영상 생성 시 시작 프레임(image-to-video)으로 사용됩니다.
    진행률은 WebSocket(`/api/storyboards/ws/{id}`)으로 확인 가능합니다.

    - 유저당 동시 최대 3개 생성 (429 반환)
    - 프리셋/커스텀 캐릭터 중 하나만 선택 필수
    """
    if not req.character_id and not req.custom_character_id:
        raise HTTPException(status_code=400, detail="캐릭터를 선택해주세요")
    if req.character_id and req.custom_character_id:
        raise HTTPException(
            status_code=400,
            detail="프리셋/커스텀 캐릭터 중 하나만 선택해주세요",
        )

    # 동시 생성 제한 (유저별)
    generating_count = await db.storyboard.count(
        where={
            "userId": current_user["id"],
            "status": "GENERATING",
        }
    )
    if generating_count >= _MAX_CONCURRENT_PER_USER:
        raise HTTPException(
            status_code=429,
            detail=f"동시에 최대 {_MAX_CONCURRENT_PER_USER}개까지 생성할 수 있습니다",
        )

    # 캐릭터 정보 조회 (설명 + 음성 설정)
    try:
        char_info = await get_character_info(req.character_id, req.custom_character_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None

    # DB에 GENERATING 상태로 생성
    record = await db.storyboard.create(
        data={
            "idea": req.idea,
            "characterId": req.character_id,
            "customCharacterId": req.custom_character_id,
            "userId": current_user["id"],
        }
    )

    # 백그라운드 태스크 시작
    cb = _make_progress_callback(record.id)
    task = asyncio.create_task(
        process_storyboard(
            storyboard_id=record.id,
            user_id=current_user["id"],
            character_desc=char_info.description,
            idea=req.idea,
            progress_callback=cb,
            voice_id=char_info.voice_id,
            voice_style=char_info.voice_style,
        )
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    return StoryboardCreateResponse(id=record.id)


@router.get(
    "",
    response_model=StoryboardListResponse,
    summary="내 콘티 목록",
    responses={
        401: {"model": ErrorResponse, "description": "인증 필요"},
    },
)
async def list_storyboards(
    current_user: dict = Depends(get_current_user),
) -> StoryboardListResponse:
    """내가 만든 콘티 목록 조회"""
    records = await db.storyboard.find_many(
        where={"userId": current_user["id"]},
        order={"createdAt": "desc"},
        take=50,
        include={"scenes": True},
    )
    items = [
        StoryboardListItem(
            id=r.id,
            idea=r.idea[:100],
            status=r.status,
            scene_count=len(r.scenes) if r.scenes else 0,
            total_duration=(sum(s.duration for s in r.scenes) if r.scenes else 0),
            created_at=r.createdAt.isoformat(),
        )
        for r in records
    ]
    return StoryboardListResponse(storyboards=items, total=len(items))


@router.get(
    "/{storyboard_id}",
    response_model=StoryboardDetailResponse,
    summary="콘티 상세 조회",
    responses={
        401: {"model": ErrorResponse, "description": "인증 필요"},
        404: {"model": ErrorResponse, "description": "콘티를 찾을 수 없음"},
    },
)
async def get_storyboard(
    storyboard_id: str,
    current_user: dict = Depends(get_current_user),
) -> StoryboardDetailResponse:
    """콘티 상세 조회 (장면 포함)"""
    record = await db.storyboard.find_first(
        where={"id": storyboard_id, "userId": current_user["id"]},
        include={"scenes": True},
    )
    if not record:
        raise HTTPException(status_code=404, detail="콘티를 찾을 수 없습니다")

    raw_scenes = sorted(record.scenes or [], key=lambda s: s.sceneOrder)
    scenes = [
        SceneItem(
            id=s.id,
            scene_order=s.sceneOrder,
            title=s.title,
            content=s.content,
            image_prompt=s.imagePrompt,
            image_url=s.imageUrl,
            image_status=s.imageStatus,
            has_character=s.hasCharacter,
            duration=s.duration,
            narration=s.narration,
            narration_style=s.narrationStyle,
            narration_url=s.narrationUrl,
            video_url=s.videoUrl,
            video_status=s.videoStatus,
            video_error=s.videoError,
        )
        for s in raw_scenes
    ]
    total_dur = sum(s.duration for s in scenes)

    return StoryboardDetailResponse(
        id=record.id,
        idea=record.idea,
        character_id=record.characterId,
        custom_character_id=record.customCharacterId,
        status=record.status,
        error_msg="생성에 실패했습니다" if record.errorMsg else None,
        bgm_mood=record.bgmMood,
        final_video_url=record.finalVideoUrl,
        scenes=scenes,
        total_duration=total_dur,
        created_at=record.createdAt.isoformat(),
    )


@router.patch(
    "/{storyboard_id}/scenes/{scene_id}",
    response_model=SceneItem,
    summary="장면 내용 수정",
    responses={
        401: {"model": ErrorResponse, "description": "인증 필요"},
        404: {"model": ErrorResponse, "description": "장면을 찾을 수 없음"},
    },
)
async def update_scene(
    storyboard_id: str,
    scene_id: str,
    req: SceneUpdateRequest,
    current_user: dict = Depends(get_current_user),
) -> SceneItem:
    """콘티 장면 내용(제목/내용) 수정

    content(설명)를 변경하면 imageStatus가 STALE로 바뀝니다.
    STALE 상태에서 이미지 재생성을 요청하면 변경된 내용 기반으로
    새 이미지 프롬프트를 생성합니다.
    """
    # 소유권 확인
    sb = await db.storyboard.find_first(where={"id": storyboard_id, "userId": current_user["id"]})
    if not sb:
        raise HTTPException(status_code=404, detail="콘티를 찾을 수 없습니다")

    scene = await db.storyboardscene.find_first(
        where={"id": scene_id, "storyboardId": storyboard_id}
    )
    if not scene:
        raise HTTPException(status_code=404, detail="장면을 찾을 수 없습니다")

    update_data: dict = {}
    if req.title is not None:
        update_data["title"] = req.title
    if req.content is not None:
        update_data["content"] = req.content
        # content 변경 시 이미지와 불일치 → STALE로 표시
        if scene.imageStatus == "COMPLETED":
            update_data["imageStatus"] = "STALE"

    if not update_data:
        raise HTTPException(status_code=400, detail="수정할 내용이 없습니다")

    updated = await db.storyboardscene.update(
        where={"id": scene_id},
        data=update_data,
    )
    return SceneItem(
        id=updated.id,
        scene_order=updated.sceneOrder,
        title=updated.title,
        content=updated.content,
        image_prompt=updated.imagePrompt,
        image_url=updated.imageUrl,
        image_status=updated.imageStatus,
        has_character=updated.hasCharacter,
        duration=updated.duration,
        narration=updated.narration,
        narration_style=updated.narrationStyle,
        narration_url=updated.narrationUrl,
        video_url=updated.videoUrl,
        video_status=updated.videoStatus,
        video_error=updated.videoError,
    )


@router.post(
    "/{storyboard_id}/scenes/{scene_id}/regenerate-image",
    response_model=SceneImageRegenerateResponse,
    summary="장면 이미지 재생성",
    responses={
        401: {"model": ErrorResponse, "description": "인증 필요"},
        404: {"model": ErrorResponse, "description": "장면을 찾을 수 없음"},
    },
)
async def regenerate_scene_image(
    storyboard_id: str,
    scene_id: str,
    current_user: dict = Depends(get_current_user),
) -> SceneImageRegenerateResponse:
    """장면 이미지 재생성 시작

    현재 장면의 content(설명)를 GPT-4o-mini로 영문 이미지 프롬프트로 변환 후,
    gpt-image-1로 새 시작 프레임을 생성합니다.
    이미 생성 중이면 409를 반환합니다.
    진행률은 WebSocket(`/api/storyboards/ws/scenes/{scene_id}/image`)으로 확인 가능합니다.
    """
    sb = await db.storyboard.find_first(where={"id": storyboard_id, "userId": current_user["id"]})
    if not sb:
        raise HTTPException(status_code=404, detail="콘티를 찾을 수 없습니다")

    scene = await db.storyboardscene.find_first(
        where={"id": scene_id, "storyboardId": storyboard_id}
    )
    if not scene:
        raise HTTPException(status_code=404, detail="장면을 찾을 수 없습니다")

    # 이미 생성 중인 장면 중복 요청 방어
    if scene.imageStatus == "GENERATING":
        raise HTTPException(
            status_code=409,
            detail="이미 이미지를 생성하고 있습니다",
        )

    # 캐릭터 설명 조회
    try:
        char_info = await get_character_info(sb.characterId, sb.customCharacterId)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None

    cb = _make_progress_callback(scene_id)
    task = asyncio.create_task(
        regenerate_scene_image_task(
            scene_id=scene_id,
            character_desc=char_info.description,
            user_id=current_user["id"],
            progress_callback=cb,
        )
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    return SceneImageRegenerateResponse(scene_id=scene_id)


# ── WebSocket: 콘티 생성 진행률 ──


@router.websocket("/ws/{storyboard_id}")
async def storyboard_progress_ws(
    ws: WebSocket,
    storyboard_id: str,
) -> None:
    """콘티 생성 진행률 WebSocket"""
    await ws.accept()

    # 쿠키 기반 인증
    user_id = await _authenticate_ws(ws)
    if not user_id:
        await ws.send_text(json.dumps({"error": "인증이 필요합니다"}))
        await ws.close(code=4001)
        return

    # 소유권 확인
    record = await db.storyboard.find_first(where={"id": storyboard_id, "userId": user_id})
    if not record:
        await ws.send_text(json.dumps({"error": "콘티를 찾을 수 없습니다"}))
        await ws.close(code=4004)
        return

    # 현재 상태 즉시 전송
    status = record.status
    progress = 100 if status == "READY" else (0 if status == "GENERATING" else -1)
    await ws.send_text(
        json.dumps(
            {
                "id": storyboard_id,
                "progress": max(progress, 0),
                "step": (
                    "완료"
                    if status == "READY"
                    else ("생성 중" if status == "GENERATING" else "실패")
                ),
                "status": status,
            },
            ensure_ascii=False,
        )
    )

    if status != "GENERATING":
        await ws.close()
        return

    if storyboard_id not in _progress_subs:
        _progress_subs[storyboard_id] = set()
    _progress_subs[storyboard_id].add(ws)

    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        _progress_subs.get(storyboard_id, set()).discard(ws)
        if storyboard_id in _progress_subs and not _progress_subs[storyboard_id]:
            del _progress_subs[storyboard_id]


# ── REST: 영상 생성 ──


@router.post(
    "/{storyboard_id}/generate-videos",
    response_model=VideoGenerationStartResponse,
    status_code=202,
    summary="콘티 영상 생성",
    responses={
        400: {
            "model": ErrorResponse,
            "description": "콘티 상태 오류 (이미지 미완성 등)",
        },
        401: {"model": ErrorResponse, "description": "인증 필요"},
        404: {"model": ErrorResponse, "description": "콘티를 찾을 수 없음"},
        409: {
            "model": ErrorResponse,
            "description": "이미 영상 생성 중",
        },
    },
)
async def generate_storyboard_videos(
    storyboard_id: str,
    current_user: dict = Depends(get_current_user),
) -> VideoGenerationStartResponse:
    """콘티의 모든 장면에 대해 Kling AI 영상 생성 시작

    콘티 상태가 READY이고 모든 장면 이미지가 완성(COMPLETED)된 경우에만
    영상 생성이 가능합니다. 장면 이미지가 있으면 Kling image-to-video,
    없으면 text-to-video로 자동 선택됩니다.
    각 장면은 병렬로 처리되며(최대 3개 동시), 진행률은
    WebSocket(`/api/storyboards/ws/{id}/video`)으로 확인 가능합니다.

    - 프롬프트 최적화: 캐릭터 외형 고정 + 조명/카메라 자동 선택
    - 개별 장면 실패 시에도 나머지 장면은 계속 생성
    - 성공한 장면은 자동으로 합본 영상 생성
    - 실패한 장면에는 실패 사유(video_error) 포함
    """
    record = await db.storyboard.find_first(
        where={
            "id": storyboard_id,
            "userId": current_user["id"],
        },
        include={"scenes": True},
    )
    if not record:
        raise HTTPException(status_code=404, detail="콘티를 찾을 수 없습니다")

    if record.status == "VIDEO_GENERATING":
        raise HTTPException(status_code=409, detail="이미 영상을 생성하고 있습니다")

    if record.status not in ("READY", "VIDEO_READY"):
        raise HTTPException(
            status_code=400,
            detail="콘티가 준비되지 않았습니다 (이미지 생성 완료 필요)",
        )

    # 모든 장면 이미지 완성 확인
    scenes = record.scenes or []
    incomplete = [s for s in scenes if s.imageStatus != "COMPLETED"]
    if incomplete:
        raise HTTPException(
            status_code=400,
            detail=(f"{len(incomplete)}개 장면의 이미지가 아직 완성되지 않았습니다"),
        )

    # 영상 생성 콜백 (dict 메시지를 JSON으로 전송)
    video_sub_key = f"{storyboard_id}:video"

    async def video_progress_callback(msg: dict) -> None:
        subs = _progress_subs.get(video_sub_key, set())
        if not subs:
            return
        is_terminal = msg.get("status") in (
            "VIDEO_READY",
            "FAILED",
        )
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
            _progress_subs.pop(video_sub_key, None)
        else:
            for ws in dead:
                subs.discard(ws)

    task = asyncio.create_task(
        process_storyboard_videos(
            storyboard_id=storyboard_id,
            user_id=current_user["id"],
            progress_callback=video_progress_callback,
        )
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    return VideoGenerationStartResponse(storyboard_id=storyboard_id)


# ── WebSocket: 영상 생성 진행률 ──


@router.websocket("/ws/{storyboard_id}/video")
async def video_progress_ws(
    ws: WebSocket,
    storyboard_id: str,
) -> None:
    """영상 생성 진행률 WebSocket

    장면별 상태(PENDING/GENERATING/COMPLETED/FAILED),
    전체 진행률(%), 예상 남은 시간(초)을 실시간 전송합니다.
    """
    await ws.accept()

    user_id = await _authenticate_ws(ws)
    if not user_id:
        await ws.send_text(json.dumps({"error": "인증이 필요합니다"}))
        await ws.close(code=4001)
        return

    record = await db.storyboard.find_first(
        where={"id": storyboard_id, "userId": user_id},
        include={"scenes": True},
    )
    if not record:
        await ws.send_text(json.dumps({"error": "콘티를 찾을 수 없습니다"}))
        await ws.close(code=4004)
        return

    # 현재 상태 즉시 전송
    scenes = sorted(record.scenes or [], key=lambda s: s.sceneOrder)
    total = len(scenes)
    done = sum(1 for s in scenes if s.videoStatus in ("COMPLETED", "FAILED"))
    overall = int((done / total) * 100) if total > 0 else 0

    await ws.send_text(
        json.dumps(
            {
                "storyboard_id": storyboard_id,
                "status": record.status,
                "overall_progress": overall,
                "estimated_remaining_seconds": 0,
                "final_video_url": record.finalVideoUrl,
                "scenes": [
                    {
                        "id": s.id,
                        "scene_order": s.sceneOrder,
                        "video_status": s.videoStatus,
                        "video_url": s.videoUrl,
                        "error": s.videoError,
                    }
                    for s in scenes
                ],
            },
            ensure_ascii=False,
        )
    )

    if record.status not in ("VIDEO_GENERATING",):
        await ws.close()
        return

    video_sub_key = f"{storyboard_id}:video"
    if video_sub_key not in _progress_subs:
        _progress_subs[video_sub_key] = set()
    _progress_subs[video_sub_key].add(ws)

    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        _progress_subs.get(video_sub_key, set()).discard(ws)
        if video_sub_key in _progress_subs and not _progress_subs[video_sub_key]:
            del _progress_subs[video_sub_key]


@router.websocket("/ws/scenes/{scene_id}/image")
async def scene_image_progress_ws(
    ws: WebSocket,
    scene_id: str,
) -> None:
    """장면 이미지 재생성 진행률 WebSocket"""
    await ws.accept()

    # 쿠키 기반 인증
    user_id = await _authenticate_ws(ws)
    if not user_id:
        await ws.send_text(json.dumps({"error": "인증이 필요합니다"}))
        await ws.close(code=4001)
        return

    # 소유권 확인: scene → storyboard → userId
    scene = await db.storyboardscene.find_unique(
        where={"id": scene_id},
        include={"storyboard": True},
    )
    if not scene or not scene.storyboard:
        await ws.send_text(json.dumps({"error": "장면을 찾을 수 없습니다"}))
        await ws.close(code=4004)
        return
    if scene.storyboard.userId != user_id:
        await ws.send_text(json.dumps({"error": "권한이 없습니다"}))
        await ws.close(code=4003)
        return

    img_status = scene.imageStatus
    progress = (
        100 if img_status == "COMPLETED" else (0 if img_status in ("GENERATING", "PENDING") else -1)
    )
    await ws.send_text(
        json.dumps(
            {
                "id": scene_id,
                "progress": max(progress, 0),
                "step": (
                    "완료"
                    if img_status == "COMPLETED"
                    else ("생성 중" if img_status == "GENERATING" else "실패")
                ),
                "status": img_status,
            },
            ensure_ascii=False,
        )
    )

    if img_status != "GENERATING":
        await ws.close()
        return

    if scene_id not in _progress_subs:
        _progress_subs[scene_id] = set()
    _progress_subs[scene_id].add(ws)

    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        _progress_subs.get(scene_id, set()).discard(ws)
        if scene_id in _progress_subs and not _progress_subs[scene_id]:
            del _progress_subs[scene_id]
