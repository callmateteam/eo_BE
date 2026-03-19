"""영상 편집 서비스 - CRUD + Undo + 초기 editData 생성"""

from __future__ import annotations

import logging

from prisma import Json

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

    # 초기 editData 생성 (현재 씬 데이터 기반 + GPT 자막 스타일 추천)
    initial = await _build_initial_edit_data(sb)

    edit = await db.videoedit.create(
        data={
            "storyboard": {"connect": {"id": storyboard_id}},
            "user": {"connect": {"id": user_id}},
            "editData": Json(initial.model_dump()),
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
            "editData": Json(edit.editData),
        },
    )

    # 오래된 히스토리 정리
    await _prune_history(edit.id)

    # 새 상태 저장
    updated = await db.videoedit.update(
        where={"id": edit.id},
        data={
            "editData": Json(edit_data.model_dump()),
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
            "editData": Json(history.editData),
            "version": history.version,
        },
    )

    # 사용한 히스토리 삭제
    await db.videoedithistory.delete(where={"id": history.id})

    return _to_dict(updated)


async def _build_initial_edit_data(storyboard) -> EditData:
    """스토리보드의 현재 씬 데이터를 기반으로 초기 편집 상태 생성

    GPT가 씬 내용/분위기를 분석하여 자막 스타일을 자동 추천한다.
    """
    from app.schemas.video_edit import SubtitleItem
    from app.services.subtitle_recommender import recommend_subtitle_styles

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

    # GPT 자막 스타일 추천
    scene_dicts = [
        {
            "content": s.content or "",
            "narration": s.narration,
            "narrationStyle": s.narrationStyle or "none",
            "duration": s.duration,
        }
        for s in scenes
    ]

    try:
        styles = await recommend_subtitle_styles(
            scene_dicts,
            bgm_mood=storyboard.bgmMood,
            character_name=getattr(storyboard, "title", ""),
        )
    except Exception:
        logger.warning("자막 스타일 추천 실패, 기본값 사용")
        styles = [None] * len(scenes)

    # 나레이션을 GPT 추천 스타일 자막으로 변환
    subtitles = []
    elapsed = 0.0
    for i, s in enumerate(scenes):
        if s.narration and s.narrationStyle != "none":
            style = styles[i] if i < len(styles) and styles[i] else None
            item_kwargs = {
                "scene_id": s.id,
                "text": s.narration,
                "start": elapsed,
                "end": elapsed + s.duration,
            }
            if style:
                item_kwargs["style"] = style
            subtitles.append(SubtitleItem(**item_kwargs))
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


async def finalize_project(storyboard_id: str, user_id: str, title: str) -> dict | None:
    """영상 완성 처리 — 제목 저장 + 프로젝트 COMPLETED 상태

    Returns:
        완성 정보 dict 또는 None (스토리보드 없음)
    """
    sb = await db.storyboard.find_first(
        where={"id": storyboard_id, "userId": user_id},
        include={"project": True},
    )
    if not sb or not sb.finalVideoUrl:
        return None

    # 영상 길이 조회
    duration = await _get_video_duration(sb.finalVideoUrl)

    # 프로젝트 업데이트
    project = sb.project
    if project:
        await db.project.update(
            where={"id": project.id},
            data={
                "title": title,
                "status": "COMPLETED",
                "currentStage": 4,
            },
        )
        project_id = project.id
    else:
        project_id = ""

    return {
        "project_id": project_id,
        "title": title,
        "video_url": sb.finalVideoUrl,
        "thumbnail_url": sb.heroFrameUrl,
        "duration": duration,
    }


async def get_video_info(storyboard_id: str, user_id: str) -> dict | None:
    """영상 정보 조회 (생성 중이면 상태만, 완료 시 URL 포함)"""
    sb = await db.storyboard.find_first(
        where={"id": storyboard_id, "userId": user_id},
        include={"project": True, "scenes": True},
    )
    if not sb:
        return None

    project = sb.project

    # 씬별 영상 생성 상태로 전체 상태 판단
    scenes = sb.scenes or []
    video_urls = [s.videoUrl for s in scenes if s.videoUrl]
    if sb.finalVideoUrl:
        status = "READY"
    elif video_urls:
        status = "GENERATING"
    else:
        status = "GENERATING"

    duration = 0.0
    if sb.finalVideoUrl:
        duration = await _get_video_duration(sb.finalVideoUrl)

    return {
        "project_id": project.id if project else "",
        "title": project.title if project else "",
        "status": status,
        "video_url": sb.finalVideoUrl,
        "thumbnail_url": sb.heroFrameUrl,
        "duration": duration,
        "created_at": sb.createdAt.isoformat(),
    }


async def _get_video_duration(video_url: str) -> float:
    """ffprobe로 영상 길이 조회 (S3 URL 직접 조회)"""
    import asyncio

    cmd = [
        "ffprobe",
        "-v",
        "quiet",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        video_url,
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        return round(float(stdout.decode().strip()), 2)
    except Exception:
        logger.warning("영상 길이 조회 실패: %s", video_url)
        return 0.0


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
