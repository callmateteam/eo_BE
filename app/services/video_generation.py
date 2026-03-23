"""콘티 기반 영상 생성 파이프라인"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Awaitable, Callable

import httpx

from app.core.database import db
from app.core.s3 import upload_video
from app.core.timezone import now_kst
from app.services.prompt_optimizer import build_hailuo_prompt, select_best_image
from app.services.storyboard import get_character_description
from app.services.video import get_generator
from app.services.video_merge import SceneInput, merge_storyboard_video

# 순환 임포트 방지: 함수 내에서 import

logger = logging.getLogger(__name__)

# 동시 영상 생성 제한 (장면 단위)
_VIDEO_SEMAPHORE = asyncio.Semaphore(2)  # Hailuo 동시 2개

# 장면당 예상 소요시간 (초) — 실측 데이터 없을 때 기본값
_DEFAULT_SCENE_DURATION_ESTIMATE = 30


async def process_storyboard_videos(
    storyboard_id: str,
    user_id: str,
    progress_callback: Callable[[dict], Awaitable[None]] | None = None,
    failed_only: bool = False,
) -> None:
    """콘티의 모든 장면에 대해 병렬로 영상 생성

    failed_only=True이면 FAILED 상태 씬만 재생성한다.
    """
    try:
        # 콘티 + 장면 조회
        storyboard = await db.storyboard.find_unique(
            where={"id": storyboard_id},
            include={"scenes": True},
        )
        if not storyboard or not storyboard.scenes:
            logger.error("콘티를 찾을 수 없음: %s", storyboard_id)
            return

        all_scenes = sorted(storyboard.scenes, key=lambda s: s.sceneOrder)
        total = len(all_scenes)

        # FAILED 씬만 필터
        if failed_only:
            scenes = [s for s in all_scenes if s.videoStatus == "FAILED"]
            if not scenes:
                logger.info("재시도할 FAILED 씬 없음: %s", storyboard_id)
                return
            logger.info("FAILED 씬 %d개 재시도: %s", len(scenes), [s.sceneOrder for s in scenes])
        else:
            scenes = all_scenes

        # 캐릭터 설명 조회
        char_desc = await get_character_description(
            storyboard.characterId, storyboard.customCharacterId
        )

        # 상태 업데이트: VIDEO_GENERATING
        await db.storyboard.update(
            where={"id": storyboard_id},
            data={"status": "VIDEO_GENERATING"},
        )

        # 대상 장면 videoStatus → GENERATING
        now = now_kst()
        for scene in scenes:
            await db.storyboardscene.update(
                where={"id": scene.id},
                data={"videoStatus": "GENERATING", "videoStartedAt": now, "videoError": None},
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
        updated_scenes = await db.storyboardscene.find_many(where={"storyboardId": storyboard_id})
        all_failed = all(s.videoStatus == "FAILED" for s in updated_scenes)

        if all_failed:
            await db.storyboard.update(
                where={"id": storyboard_id},
                data={"status": "FAILED"},
            )
            await _send_progress(
                storyboard_id,
                updated_scenes,
                total,
                total,
                start_time,
                completed_durations,
                progress_callback,
                terminal=True,
            )
            return

        # 성공한 장면이 있으면 최종 합본 영상 생성
        await _send_progress(
            storyboard_id,
            updated_scenes,
            total,
            total,
            start_time,
            completed_durations,
            progress_callback,
        )

        completed_scenes = [
            s for s in updated_scenes if s.videoStatus == "COMPLETED" and s.videoUrl
        ]
        failed_url_scenes = [
            s for s in updated_scenes if s.videoStatus == "COMPLETED" and not s.videoUrl
        ]
        if failed_url_scenes:
            logger.error(
                "videoStatus=COMPLETED but videoUrl=None인 씬 %d개 발견! scene_ids=%s",
                len(failed_url_scenes),
                [s.id for s in failed_url_scenes],
            )

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
        final_scenes = await db.storyboardscene.find_many(where={"storyboardId": storyboard_id})
        await _send_progress(
            storyboard_id,
            final_scenes,
            total,
            total,
            start_time,
            completed_durations,
            progress_callback,
            terminal=True,
        )

        # 프로젝트 4단계(영상완료) 자동 진행
        if not all_failed:
            await _advance_project_stage(storyboard_id)

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
        try:
            generator = get_generator()

            # 캐릭터 정보에서 시드 데이터 추출
            char_info = await _get_character_seed_data(storyboard_id)

            # Hailuo 프롬프트 v3 (배경 컨텍스트 + motionPrompt + enrichedIdea)
            hailuo_result = build_hailuo_prompt(
                scene_content=scene.content,
                image_prompt=getattr(scene, "imagePrompt", None),
                motion_prompt=getattr(scene, "motionPrompt", None),
                character_name=char_info.get("name", ""),
                veo_prompt=char_info.get("veo_prompt", ""),
                world_context=char_info.get("world_context", ""),
                art_style=char_info.get("art_style", ""),
                series_description=char_info.get("series_description", ""),
                secondary_character=getattr(scene, "secondaryCharacter", "") or "",
                secondary_character_desc=getattr(scene, "secondaryCharacterDesc", "") or "",
                bgm_mood=bgm_mood,
                enriched_background=char_info.get("enriched_background", ""),
                enriched_mood=char_info.get("enriched_mood", ""),
                scene_order=scene.sceneOrder,
                total_scenes=total,
                duration=int(scene.duration),
            )

            prompt = hailuo_result["prompt"]

            # 씬 이미지 사용 (FLUX가 생성한 9:16 이미지)
            # fallback 이미지(캐릭터 원본)면 자동 재생성 시도
            scene_image = scene.imageUrl or ""
            is_fallback = "characters/" in scene_image and "/image" in scene_image
            if is_fallback or not scene_image:
                logger.info("fallback 이미지 감지, 자동 재생성: scene=%s", scene.id)
                try:
                    from app.services.storyboard import generate_scene_image
                    new_url, _ = await generate_scene_image(
                        image_prompt=scene.imagePrompt or "",
                        character_desc=char_info.get("description", ""),
                        user_id=user_id,
                        reference_image_url=char_info.get("image_url", ""),
                        art_style=char_info.get("art_style", ""),
                        world_context=char_info.get("world_context", ""),
                    )
                    await db.storyboardscene.update(
                        where={"id": scene.id},
                        data={"imageUrl": new_url, "imageStatus": "COMPLETED"},
                    )
                    scene_image = new_url
                    logger.info("이미지 자동 재생성 성공: scene=%s", scene.id)
                except Exception:
                    logger.exception("이미지 자동 재생성 실패, 원본 사용: scene=%s", scene.id)
                    scene_image = scene_image or char_info.get("image_url", "")
            image_url = scene_image

            # 영상 생성 → URL 반환
            result_url = await generator.generate(
                prompt=prompt,
                image_url=image_url,
                duration=int(scene.duration),
                aspect_ratio="1:1",
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
            logger.info(
                "영상 생성 결과 URL: scene=%s, result_url=%s",
                scene.id, result_url[:200] if result_url else "None",
            )
            video_url = await _download_and_upload(result_url, user_id)

            if not video_url:
                raise RuntimeError(
                    f"영상 S3 업로드 실패: result_url={result_url}, "
                    f"video_url=None"
                )

            await db.storyboardscene.update(
                where={"id": scene.id},
                data={
                    "videoStatus": "COMPLETED",
                    "videoUrl": video_url,
                    "videoError": None,
                },
            )
            logger.info("영상 저장 완료: scene=%s, videoUrl=%s", scene.id, video_url[:80])

            elapsed = time.monotonic() - scene_start
            completed_durations.append(elapsed)

        except Exception as exc:
            error_msg = str(exc)[:500]
            logger.warning("장면 영상 생성 실패 (1회 자동 재시도): scene_id=%s, err=%s", scene.id, error_msg[:100])

            # ── 자동 1회 재시도 ──
            retry_success = False
            try:
                logger.info("자동 재시도 시작: scene=%s", scene.id)
                await db.storyboardscene.update(
                    where={"id": scene.id},
                    data={"videoStatus": "GENERATING", "videoError": None},
                )
                retry_generator = get_generator()
                retry_url = await retry_generator.generate(
                    prompt=prompt,
                    image_url=image_url,
                    duration=int(scene.duration),
                    aspect_ratio="1:1",
                )
                retry_video_url = await _download_and_upload(retry_url, user_id)
                if retry_video_url:
                    await db.storyboardscene.update(
                        where={"id": scene.id},
                        data={
                            "videoStatus": "COMPLETED",
                            "videoUrl": retry_video_url,
                            "videoError": None,
                        },
                    )
                    logger.info("자동 재시도 성공: scene=%s", scene.id)
                    retry_success = True
            except Exception as retry_exc:
                logger.exception("자동 재시도도 실패: scene_id=%s", scene.id)
                error_msg = f"재시도 실패: {str(retry_exc)[:400]}"

            if not retry_success:
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
        updated_scenes = await db.storyboardscene.find_many(where={"storyboardId": storyboard_id})
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
        all_failed = all(item["video_status"] == "FAILED" for item in scene_items)
        status = "FAILED" if all_failed else "VIDEO_READY"
        # 최종 합본 URL 조회
        sb = await db.storyboard.find_unique(where={"id": storyboard_id})
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


async def _get_character_seed_data(storyboard_id: str) -> dict:
    """스토리보드의 캐릭터 시드 데이터 + enrichedIdea 조회"""
    sb = await db.storyboard.find_unique(
        where={"id": storyboard_id},
        include={"character": True, "customCharacter": True},
    )
    if not sb:
        return {}

    # enrichedIdea: Project에서 가져오기 (storyboardId로 연결)
    enriched_background = ""
    enriched_mood = ""
    project = await db.project.find_first(where={"storyboardId": storyboard_id})
    if project and getattr(project, "enrichedIdea", None):
        enriched = project.enrichedIdea
        if isinstance(enriched, dict):
            enriched_background = enriched.get("background", "") or ""
            enriched_mood = enriched.get("mood", "") or ""

    if sb.character:
        c = sb.character
        return {
            "name": c.name,
            "image_url": c.imageUrl,
            "art_style": getattr(c, "artStyle", "") or "",
            "extra_images": getattr(c, "extraImages", "") or "",
            "world_context": getattr(c, "worldContext", "") or "",
            "series_description": getattr(c, "seriesDescription", "") or "",
            "prompt_features": c.promptFeatures,
            "veo_prompt": getattr(c, "veoPrompt", "") or "",
            "enriched_background": enriched_background,
            "enriched_mood": enriched_mood,
        }

    if sb.customCharacter:
        cc = sb.customCharacter
        return {
            "name": cc.name,
            "image_url": cc.imageUrl1,
            "art_style": "",
            "extra_images": "",
            "world_context": "",
            "prompt_features": getattr(cc, "veoPrompt", "") or cc.description,
            "veo_prompt": getattr(cc, "veoPrompt", "") or cc.description,
            "enriched_background": enriched_background,
            "enriched_mood": enriched_mood,
        }

    return {}


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
    """영상 URL을 다운로드하여 S3에 업로드 → S3 URL 반환"""
    if not video_url:
        logger.error("영상 URL이 None — 다운로드 건너뜀")
        return None

    if not video_url.startswith("http"):
        logger.error("영상 URL이 http로 시작하지 않음: %s", video_url[:100])
        return None

    async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
        resp = await client.get(video_url)
        resp.raise_for_status()
        video_bytes = resp.content

    logger.info("영상 다운로드 완료: %d bytes", len(video_bytes))

    # ── 디버그: 다운로드된 영상의 실제 해상도 확인 ──
    await _log_video_dimensions(video_bytes)

    # ── 레터박스 적용: 720x720 → 1080x1920 (9:16) ──
    video_bytes = await _apply_letterbox(video_bytes)

    s3_url = await asyncio.to_thread(upload_video, video_bytes, user_id)
    logger.info("영상 S3 업로드 완료: %s", s3_url[:80] if s3_url else "None")
    return s3_url


async def _apply_letterbox(video_bytes: bytes) -> bytes:
    """720x720 → 1080x1920 레터박스 변환 (상하 검은 여백)"""
    import tempfile

    tmp_in = None
    tmp_out = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            f.write(video_bytes)
            tmp_in = f.name
        tmp_out = tmp_in.replace(".mp4", "_lb.mp4")

        cmd = [
            "ffmpeg", "-y", "-i", tmp_in,
            "-vf", "scale=1080:1080:force_original_aspect_ratio=decrease,"
                   "pad=1080:1920:0:420:black",
            "-c:a", "copy",
            "-c:v", "libx264", "-crf", "18", "-preset", "fast",
            "-movflags", "+faststart",
            tmp_out,
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.error("레터박스 ffmpeg 실패: %s", stderr.decode()[-500:])
            return video_bytes  # 실패 시 원본 반환

        with open(tmp_out, "rb") as f:
            result = f.read()
        logger.info("레터박스 적용 완료: %d → %d bytes", len(video_bytes), len(result))
        return result
    except Exception:
        logger.exception("레터박스 적용 예외, 원본 사용")
        return video_bytes
    finally:
        for p in (tmp_in, tmp_out):
            if p and os.path.exists(p):
                os.unlink(p)


async def _log_video_dimensions(video_bytes: bytes) -> None:
    """영상 바이트에서 해상도를 ffprobe로 확인하여 로깅"""
    import tempfile

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp.write(video_bytes)
            tmp_path = tmp.name

        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height,duration,codec_name",
            "-of", "json",
            tmp_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode == 0:
            import json
            info = json.loads(stdout.decode())
            streams = info.get("streams", [])
            if streams:
                s = streams[0]
                logger.info(
                    "[디버그] 영상 해상도: %sx%s, codec=%s, duration=%s",
                    s.get("width"), s.get("height"),
                    s.get("codec_name"), s.get("duration"),
                )
            else:
                logger.warning("[디버그] ffprobe 스트림 정보 없음")
        else:
            logger.warning(
                "[디버그] ffprobe 실패 (code=%d): %s",
                proc.returncode, stderr.decode()[:200],
            )
    except FileNotFoundError:
        logger.warning("[디버그] ffprobe 미설치 — 영상 해상도 확인 불가")
    except Exception:
        logger.warning("[디버그] 영상 해상도 확인 중 오류", exc_info=True)
    finally:
        if tmp_path:
            import os
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


async def _advance_project_stage(storyboard_id: str) -> None:
    """스토리보드에 연결된 프로젝트를 4단계(영상완료)로 진행한다."""
    from app.services.project import advance_to_video_complete

    project = await db.project.find_first(where={"storyboardId": storyboard_id})
    if project:
        await advance_to_video_complete(project.id)
