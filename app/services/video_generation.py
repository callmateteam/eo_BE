"""콘티 기반 영상 생성 파이프라인"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

import httpx

from app.core.database import db
from app.core.s3 import upload_video
from app.core.timezone import now_kst
from app.services.prompt_optimizer import optimize_scene_prompt
from app.services.storyboard import get_character_description
from app.services.video import get_generator
from app.services.video_merge import SceneInput, merge_storyboard_video

logger = logging.getLogger(__name__)

# 동시 영상 생성 제한 (장면 단위)
_VIDEO_SEMAPHORE = asyncio.Semaphore(1)  # Veo rate limit 대응: 순차 1개씩

# 장면당 예상 소요시간 (초) — 실측 데이터 없을 때 기본값
_DEFAULT_SCENE_DURATION_ESTIMATE = 30


async def process_storyboard_videos(
    storyboard_id: str,
    user_id: str,
    progress_callback: Callable[[dict], Awaitable[None]] | None = None,
) -> None:
    """콘티의 모든 장면에 대해 병렬로 영상 생성"""
    try:
        # 콘티 + 장면 조회
        storyboard = await db.storyboard.find_unique(
            where={"id": storyboard_id},
            include={"scenes": True},
        )
        if not storyboard or not storyboard.scenes:
            logger.error("콘티를 찾을 수 없음: %s", storyboard_id)
            return

        scenes = sorted(storyboard.scenes, key=lambda s: s.sceneOrder)
        total = len(scenes)

        # 캐릭터 설명 조회
        char_desc = await get_character_description(
            storyboard.characterId, storyboard.customCharacterId
        )

        # 상태 업데이트: VIDEO_GENERATING
        await db.storyboard.update(
            where={"id": storyboard_id},
            data={"status": "VIDEO_GENERATING"},
        )

        # 모든 장면 videoStatus → GENERATING
        now = now_kst()
        for scene in scenes:
            await db.storyboardscene.update(
                where={"id": scene.id},
                data={"videoStatus": "GENERATING", "videoStartedAt": now},
            )

        # 초기 진행률 전송
        await _send_progress(
            storyboard_id, scenes, 0, total, time.monotonic(), [], progress_callback
        )

        # 완료 추적
        completed_durations: list[float] = []
        start_time = time.monotonic()

        # bgm_mood 추출 (첫 장면의 bgmMood 또는 storyboard 레벨)
        bgm_mood = getattr(storyboard, "bgmMood", None)

        # 장면별 병렬 생성
        tasks = [
            asyncio.create_task(
                _generate_scene_video(
                    scene=scene,
                    char_desc=char_desc,
                    user_id=user_id,
                    storyboard_id=storyboard_id,
                    total=total,
                    start_time=start_time,
                    completed_durations=completed_durations,
                    progress_callback=progress_callback,
                    bgm_mood=bgm_mood,
                )
            )
            for scene in scenes
        ]

        await asyncio.gather(*tasks, return_exceptions=True)

        # 최종 상태 확인
        updated_scenes = await db.storyboardscene.find_many(
            where={"storyboardId": storyboard_id}
        )
        all_failed = all(s.videoStatus == "FAILED" for s in updated_scenes)

        if all_failed:
            await db.storyboard.update(
                where={"id": storyboard_id},
                data={"status": "FAILED"},
            )
            await _send_progress(
                storyboard_id, updated_scenes, total, total,
                start_time, completed_durations, progress_callback,
                terminal=True,
            )
            return

        # 성공한 장면이 있으면 최종 합본 영상 생성
        await _send_progress(
            storyboard_id, updated_scenes, total, total,
            start_time, completed_durations, progress_callback,
        )

        completed_scenes = [
            s for s in updated_scenes
            if s.videoStatus == "COMPLETED" and s.videoUrl
        ]

        if completed_scenes:
            try:
                scene_inputs = [
                    SceneInput(
                        scene_order=s.sceneOrder,
                        video_url=s.videoUrl,
                        duration=s.duration,
                        narration=s.narration,
                        narration_style=s.narrationStyle,
                        narration_url=s.narrationUrl,
                    )
                    for s in completed_scenes
                ]
                final_url = await merge_storyboard_video(
                    scenes=scene_inputs,
                    user_id=user_id,
                    bgm_mood=storyboard.bgmMood,
                )
                await db.storyboard.update(
                    where={"id": storyboard_id},
                    data={
                        "status": "VIDEO_READY",
                        "finalVideoUrl": final_url,
                    },
                )
            except Exception:
                logger.exception("최종 영상 합성 실패: %s", storyboard_id)
                await db.storyboard.update(
                    where={"id": storyboard_id},
                    data={"status": "VIDEO_READY"},
                )
        else:
            await db.storyboard.update(
                where={"id": storyboard_id},
                data={"status": "VIDEO_READY"},
            )

        # 최종 진행률 전송
        final_scenes = await db.storyboardscene.find_many(
            where={"storyboardId": storyboard_id}
        )
        await _send_progress(
            storyboard_id, final_scenes, total, total,
            start_time, completed_durations, progress_callback,
            terminal=True,
        )

    except Exception:
        logger.exception("영상 생성 파이프라인 실패: %s", storyboard_id)
        await db.storyboard.update(
            where={"id": storyboard_id},
            data={"status": "FAILED", "errorMsg": "영상 생성 중 오류가 발생했습니다."},
        )


async def _generate_scene_video(
    *,
    scene,
    char_desc: str,
    user_id: str,
    storyboard_id: str,
    total: int,
    start_time: float,
    completed_durations: list[float],
    progress_callback: Callable[[dict], Awaitable[None]] | None,
    bgm_mood: str | None = None,
) -> None:
    """개별 장면 영상 생성 (세마포어 제한 + 프롬프트 최적화)"""
    scene_start = time.monotonic()

    async with _VIDEO_SEMAPHORE:
        # Veo rate limit 방지: 장면 순서에 따라 딜레이
        if scene.sceneOrder > 1:
            delay = (scene.sceneOrder - 1) * 15
            logger.info("Veo rate limit 방지: 장면%d, %d초 대기", scene.sceneOrder, delay)
            await asyncio.sleep(delay)

        try:
            generator = get_generator()

            # 프롬프트 최적화 (가성비 극대화)
            prompt = optimize_scene_prompt(
                scene_content=scene.content,
                character_desc=char_desc,
                image_prompt=getattr(scene, "imagePrompt", None),
                has_character=getattr(scene, "hasCharacter", True),
                bgm_mood=bgm_mood,
                scene_order=scene.sceneOrder,
                total_scenes=total,
                duration=int(scene.duration),
            )

            # 영상 생성 → URL 반환
            result_url = await generator.generate(
                prompt=prompt,
                image_url=scene.imageUrl,
                duration=int(scene.duration),
                aspect_ratio="9:16",
            )

            # 비용 로깅
            logger.info(
                "[비용] scene=%d, provider=%s, duration=%ds, prompt_len=%d",
                scene.sceneOrder,
                generator.provider_name,
                int(scene.duration),
                len(prompt),
            )

            # 영상 URL → S3 업로드
            video_url = await _download_and_upload(
                result_url, user_id
            )

            await db.storyboardscene.update(
                where={"id": scene.id},
                data={
                    "videoStatus": "COMPLETED",
                    "videoUrl": video_url,
                    "videoError": None,
                },
            )

            elapsed = time.monotonic() - scene_start
            completed_durations.append(elapsed)

        except Exception as exc:
            error_msg = str(exc)[:500]
            logger.exception("장면 영상 생성 실패: scene_id=%s", scene.id)

            await db.storyboardscene.update(
                where={"id": scene.id},
                data={
                    "videoStatus": "FAILED",
                    "videoError": error_msg,
                },
            )

            completed_durations.append(time.monotonic() - scene_start)

        # 진행률 업데이트
        done_count = len(completed_durations)
        updated_scenes = await db.storyboardscene.find_many(
            where={"storyboardId": storyboard_id}
        )
        await _send_progress(
            storyboard_id,
            updated_scenes,
            done_count,
            total,
            start_time,
            completed_durations,
            progress_callback,
        )


async def _send_progress(
    storyboard_id: str,
    scenes,
    done_count: int,
    total: int,
    start_time: float,
    completed_durations: list[float],
    callback: Callable[[dict], Awaitable[None]] | None,
    *,
    terminal: bool = False,
) -> None:
    """진행률 WS 메시지 전송"""
    if callback is None:
        return

    overall = int((done_count / total) * 100) if total > 0 else 0
    remaining = _estimate_remaining(done_count, total, completed_durations)

    sorted_scenes = sorted(scenes, key=lambda s: s.sceneOrder)
    scene_items = [
        {
            "id": s.id,
            "scene_order": s.sceneOrder,
            "video_status": s.videoStatus,
            "video_url": s.videoUrl if hasattr(s, "videoUrl") else None,
            "error": s.videoError if hasattr(s, "videoError") else None,
        }
        for s in sorted_scenes
    ]

    status = "VIDEO_GENERATING"
    final_video_url = None
    if terminal:
        all_failed = all(
            item["video_status"] == "FAILED" for item in scene_items
        )
        status = "FAILED" if all_failed else "VIDEO_READY"
        # 최종 합본 URL 조회
        sb = await db.storyboard.find_unique(
            where={"id": storyboard_id}
        )
        if sb:
            final_video_url = sb.finalVideoUrl

    msg = {
        "storyboard_id": storyboard_id,
        "status": status,
        "overall_progress": overall,
        "estimated_remaining_seconds": remaining,
        "final_video_url": final_video_url,
        "scenes": scene_items,
    }

    await callback(msg)


def _estimate_remaining(
    done_count: int,
    total: int,
    completed_durations: list[float],
) -> int:
    """예상 남은 시간 (초) 계산"""
    remaining_count = total - done_count
    if remaining_count <= 0:
        return 0

    if not completed_durations:
        return remaining_count * _DEFAULT_SCENE_DURATION_ESTIMATE

    avg = sum(completed_durations) / len(completed_durations)
    # 세마포어 3개로 병렬 처리 → 동시 3개씩
    parallel_batches = (remaining_count + 2) // 3
    return int(avg * parallel_batches)


async def _download_and_upload(
    video_url: str | None,
    user_id: str,
) -> str | None:
    """영상 URL을 다운로드하여 S3에 업로드 → S3 URL 반환

    Mock(url=task_id_hex)이면 None 반환.
    """
    if not video_url or not video_url.startswith("http"):
        return None

    async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
        resp = await client.get(video_url)
        resp.raise_for_status()
        video_bytes = resp.content

    s3_url = await asyncio.to_thread(
        upload_video, video_bytes, user_id
    )
    return s3_url
