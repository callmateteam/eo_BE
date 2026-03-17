"""영상 편집 서비스 - CRUD + Undo + 초기 editData 생성"""

from __future__ import annotations

import logging

from app.core.database import db
from app.schemas.video_edit import EditData, SceneEditItem

logger = logging.getLogger(__name__)

# 되돌리기 히스토리 최대 보관 수
_MAX_HISTORY = 50


async def get_or_create_edit(storyboard_id: str, user_id: str) -> dict | None:
    """편집 상태 조회 (없으면 스토리보드 기반 초기값 자동 생성)"""
    # 소유권 확인
    sb = await db.storyboard.find_first(
        where={"id": storyboard_id, "userId": user_id},
        include={"scenes": True},
    )
    if not sb:
        return None

    edit = await db.videoedit.find_unique(where={"storyboardId": storyboard_id})
    if edit:
        return _to_dict(edit)

    # 초기 editData 생성 (현재 씬 데이터 기반)
    initial = _build_initial_edit_data(sb)

    edit = await db.videoedit.create(
        data={
            "storyboardId": storyboard_id,
            "userId": user_id,
            "editData": initial.model_dump(),
            "version": 1,
        },
    )
    return _to_dict(edit)


async def update_edit(storyboard_id: str, user_id: str, edit_data: EditData) -> dict | None:
    """편집 저장 (version 증가 + 히스토리 자동 생성)"""
    edit = await db.videoedit.find_first(
        where={"storyboardId": storyboard_id, "userId": user_id},
    )
    if not edit:
        # 아직 편집 상태가 없으면 먼저 생성
        result = await get_or_create_edit(storyboard_id, user_id)
        if not result:
            return None
        edit = await db.videoedit.find_unique(where={"storyboardId": storyboard_id})
        if not edit:
            return None

    # 현재 상태를 히스토리에 저장
    await db.videoedithistory.create(
        data={
            "editId": edit.id,
            "version": edit.version,
            "editData": edit.editData,
        },
    )

    # 오래된 히스토리 정리
    await _prune_history(edit.id)

    # 새 상태 저장
    updated = await db.videoedit.update(
        where={"id": edit.id},
        data={
            "editData": edit_data.model_dump(),
            "version": edit.version + 1,
        },
    )
    return _to_dict(updated)


async def undo_edit(storyboard_id: str, user_id: str) -> dict | None:
    """한 단계 되돌리기 (이전 version 히스토리 복원)

    Returns:
        복원된 편집 상태 dict, 히스토리 없으면 None
    """
    edit = await db.videoedit.find_first(
        where={"storyboardId": storyboard_id, "userId": user_id},
    )
    if not edit:
        return None

    # 가장 최근 히스토리 조회
    history = await db.videoedithistory.find_first(
        where={"editId": edit.id},
        order={"version": "desc"},
    )
    if not history:
        return None

    # 히스토리 데이터로 복원
    updated = await db.videoedit.update(
        where={"id": edit.id},
        data={
            "editData": history.editData,
            "version": history.version,
        },
    )

    # 사용한 히스토리 삭제
    await db.videoedithistory.delete(where={"id": history.id})

    return _to_dict(updated)


def _build_initial_edit_data(storyboard) -> EditData:
    """스토리보드의 현재 씬 데이터를 기반으로 초기 편집 상태 생성"""
    scenes = sorted(storyboard.scenes or [], key=lambda s: s.sceneOrder)

    scene_edits = [
        SceneEditItem(
            scene_id=s.id,
            order=s.sceneOrder,
            trim_start=0.0,
            trim_end=s.duration,
            speed=1.0,
        )
        for s in scenes
    ]

    # 기존 나레이션을 자막으로 변환
    subtitles = []
    elapsed = 0.0
    for s in scenes:
        if s.narration and s.narrationStyle != "none":
            from app.schemas.video_edit import SubtitleItem

            subtitles.append(
                SubtitleItem(
                    scene_id=s.id,
                    text=s.narration,
                    start=elapsed,
                    end=elapsed + s.duration,
                )
            )
        elapsed += s.duration

    return EditData(
        scenes=scene_edits,
        bgm={"preset": storyboard.bgmMood, "volume": 0.2},
        subtitles=subtitles,
        thumbnail_time=0.0,
    )


async def _prune_history(edit_id: str) -> None:
    """오래된 히스토리 정리 (최대 _MAX_HISTORY개 유지)"""
    count = await db.videoedithistory.count(where={"editId": edit_id})
    if count <= _MAX_HISTORY:
        return

    # 가장 오래된 것부터 삭제
    oldest = await db.videoedithistory.find_many(
        where={"editId": edit_id},
        order={"version": "asc"},
        take=count - _MAX_HISTORY,
    )
    for h in oldest:
        await db.videoedithistory.delete(where={"id": h.id})


async def get_storyboard_video_url(storyboard_id: str, user_id: str) -> str | None:
    """스토리보드의 finalVideoUrl 조회 (소유권 확인 포함)"""
    sb = await db.storyboard.find_first(
        where={"id": storyboard_id, "userId": user_id},
    )
    if not sb or not sb.finalVideoUrl:
        return None
    return sb.finalVideoUrl


async def update_storyboard_thumbnail(storyboard_id: str, url: str) -> None:
    """스토리보드 heroFrameUrl 업데이트"""
    await db.storyboard.update(
        where={"id": storyboard_id},
        data={"heroFrameUrl": url},
    )


def _to_dict(edit) -> dict:
    """VideoEdit DB 레코드 → dict 변환"""
    return {
        "id": edit.id,
        "storyboard_id": edit.storyboardId,
        "edit_data": edit.editData,
        "version": edit.version,
        "created_at": edit.createdAt.isoformat(),
        "updated_at": edit.updatedAt.isoformat(),
    }
