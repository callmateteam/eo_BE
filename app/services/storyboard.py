"""콘티 생성 서비스 - GPT 장면 분할 + GPT 이미지 생성 (Veo 시작 프레임 겸용)"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from collections.abc import Awaitable, Callable

import httpx

from app.core.config import settings
from app.core.database import db
from app.core.s3 import upload_image

logger = logging.getLogger(__name__)

# ── GPT 콘티 생성 프롬프트 (토큰 최적화) ──

STORYBOARD_SYSTEM = """\
Short-form video storyboard creator.
Create scene cuts from character + idea.

Rules:
- Total ≤ 60s, each scene 3-10s
- Output ONLY valid JSON array
- 3-8 scenes
- imagePrompt: English, max 20 words, opening shot of the scene only
- title/content: Korean, concise
- duration: action=short, dialogue=longer

[{"title":"","content":"","imagePrompt":"","duration":5.0}]"""

STORYBOARD_USER = """\
캐릭터: {character_desc}
아이디어: {idea}
60초 이내 숏폼 콘티 생성."""

# 이미지 동시 요청 제한 (rate limit 방지) - 지연 초기화
_IMAGE_SEMAPHORE: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
    """이벤트 루프 시작 후 세마포어 지연 생성"""
    global _IMAGE_SEMAPHORE  # noqa: PLW0603
    if _IMAGE_SEMAPHORE is None:
        _IMAGE_SEMAPHORE = asyncio.Semaphore(3)
    return _IMAGE_SEMAPHORE


async def generate_scenes_with_gpt(
    character_desc: str,
    idea: str,
) -> list[dict]:
    """GPT-4o-mini로 콘티 장면 분할 생성 (토큰 절약)"""
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "gpt-4o-mini",
                "max_tokens": 1500,
                "temperature": 0.7,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": STORYBOARD_SYSTEM},
                    {
                        "role": "user",
                        "content": STORYBOARD_USER.format(
                            character_desc=character_desc,
                            idea=idea,
                        ),
                    },
                ],
            },
        )
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"].strip()
        parsed = json.loads(raw)

        # response_format=json_object는 객체를 반환하므로 배열 추출
        if isinstance(parsed, list):
            scenes = parsed
        else:
            # GPT가 사용할 수 있는 다양한 키 처리
            for key in ("scenes", "data", "storyboard", "cuts"):
                if key in parsed and isinstance(parsed[key], list):
                    scenes = parsed[key]
                    break
            else:
                scenes = []

        if not scenes:
            raise ValueError("GPT가 유효한 장면을 생성하지 못했습니다")

        # 필드 검증 및 정규화
        validated: list[dict] = []
        for s in scenes:
            validated.append({
                "title": str(s.get("title", "장면"))[:100],
                "content": str(s.get("content", ""))[:2000],
                "imagePrompt": str(s.get("imagePrompt", ""))[:200],
                "duration": min(
                    max(float(s.get("duration", 5.0)), 2.0), 10.0
                ),
            })

        # 총 duration 60초 초과 시 비례 조정
        total = sum(s["duration"] for s in validated)
        if total > 60:
            ratio = 60.0 / total
            for s in validated:
                s["duration"] = round(s["duration"] * ratio, 1)

        return validated


async def generate_scene_image(
    image_prompt: str,
    character_desc: str,
    user_id: str,
) -> str:
    """GPT 이미지 생성으로 장면 시작 프레임 생성 → S3 업로드 → URL 반환

    생성된 이미지는 콘티 썸네일 겸 Veo image-to-video 시작 프레임으로 사용됩니다.
    """
    full_prompt = (
        f"{character_desc}. "
        f"Opening shot: {image_prompt}. "
        "Single frame, cinematic still, high detail."
    )[:4000]

    async with _get_semaphore():
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                "https://api.openai.com/v1/images/generations",
                headers={
                    "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "gpt-image-1",
                    "prompt": full_prompt,
                    "n": 1,
                    "size": "1024x1024",
                    "quality": "medium",
                },
            )
            resp.raise_for_status()
            result = resp.json()["data"][0]

    # gpt-image-1은 b64_json 또는 url로 반환
    if "b64_json" in result:
        img_data = base64.b64decode(result["b64_json"])
    else:
        async with httpx.AsyncClient(timeout=60) as client:
            img_resp = await client.get(result["url"])
            img_resp.raise_for_status()
            img_data = img_resp.content

    s3_url = await asyncio.to_thread(
        upload_image,
        img_data,
        user_id,
        content_type="image/png",
        folder="storyboard-scenes",
    )
    return s3_url


async def get_character_description(
    character_id: str | None,
    custom_character_id: str | None,
) -> str:
    """캐릭터 ID로 설명 텍스트 조회"""
    if character_id:
        char = await db.character.find_unique(where={"id": character_id})
        if not char:
            raise ValueError("캐릭터를 찾을 수 없습니다")
        return char.veoPrompt
    if custom_character_id:
        cc = await db.customcharacter.find_unique(
            where={"id": custom_character_id}
        )
        if not cc:
            raise ValueError("커스텀 캐릭터를 찾을 수 없습니다")
        if cc.status != "COMPLETED" or not cc.veoPrompt:
            raise ValueError("아직 생성 중이거나 실패한 캐릭터입니다")
        return cc.veoPrompt
    raise ValueError("캐릭터를 선택해주세요")


async def process_storyboard(
    storyboard_id: str,
    user_id: str,
    character_desc: str,
    idea: str,
    progress_callback: Callable[[int, str], Awaitable[None]] | None = None,
) -> None:
    """콘티 생성 전체 파이프라인 (백그라운드)"""

    async def notify(pct: int, step: str) -> None:
        if progress_callback:
            await progress_callback(pct, step)

    try:
        # Step 1: GPT 장면 분할 (0-30%)
        await notify(10, "AI가 장면을 구성하고 있습니다...")
        scenes = await generate_scenes_with_gpt(character_desc, idea)
        await notify(30, f"{len(scenes)}개 장면 생성 완료")

        # Step 2: DB에 장면 저장 (30-40%)
        await notify(35, "장면 저장 중...")
        for i, scene in enumerate(scenes):
            await db.storyboardscene.create(
                data={
                    "storyboardId": storyboard_id,
                    "sceneOrder": i + 1,
                    "title": scene["title"],
                    "content": scene["content"],
                    "imagePrompt": scene["imagePrompt"],
                    "duration": scene["duration"],
                    "imageStatus": "GENERATING",
                }
            )
        await notify(40, "장면 저장 완료")

        # Step 3: GPT 이미지 병렬 생성 (40-95%) — Veo 시작 프레임 겸용
        db_scenes = await db.storyboardscene.find_many(
            where={"storyboardId": storyboard_id},
            order={"sceneOrder": "asc"},
        )
        await notify(
            45,
            f"장면 {len(db_scenes)}개 시작 프레임 생성 중...",
        )

        async def _gen_one(sc: object) -> None:
            """단일 장면 이미지 생성 + DB 업데이트"""
            try:
                s3_url = await generate_scene_image(
                    sc.imagePrompt, character_desc, user_id
                )
                await db.storyboardscene.update(
                    where={"id": sc.id},
                    data={"imageUrl": s3_url, "imageStatus": "COMPLETED"},
                )
            except Exception:
                logger.exception("장면 이미지 생성 실패: %s", sc.id)
                await db.storyboardscene.update(
                    where={"id": sc.id},
                    data={"imageStatus": "FAILED"},
                )

        # 병렬 실행 (세마포어로 동시 3개 제한)
        await asyncio.gather(*[_gen_one(sc) for sc in db_scenes])

        # Step 4: 완료 여부 확인 (95-100%)
        failed_count = await db.storyboardscene.count(
            where={
                "storyboardId": storyboard_id,
                "imageStatus": "FAILED",
            },
        )
        if failed_count == len(db_scenes):
            raise ValueError("모든 장면 이미지 생성에 실패했습니다")

        await db.storyboard.update(
            where={"id": storyboard_id},
            data={"status": "READY"},
        )
        msg = "콘티 생성 완료!"
        if failed_count > 0:
            msg = (
                f"콘티 생성 완료 ({failed_count}개 이미지 재생성 필요)"
            )
        await notify(100, msg)

    except Exception as e:
        logger.exception("콘티 생성 실패: %s", storyboard_id)
        try:
            await db.storyboard.update(
                where={"id": storyboard_id},
                data={"status": "FAILED", "errorMsg": str(e)[:500]},
            )
        except Exception:
            logger.exception(
                "FAILED 상태 업데이트 실패: %s", storyboard_id
            )
        if progress_callback:
            await progress_callback(-1, "콘티 생성에 실패했습니다")


async def content_to_image_prompt(
    content: str,
    character_desc: str,
) -> str:
    """콘티 설명(한글)을 이미지 생성용 영문 프롬프트로 변환"""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "gpt-4o-mini",
                "max_tokens": 100,
                "temperature": 0.3,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Convert Korean scene description to "
                            "English image prompt. Max 20 words. "
                            "Opening shot only. No style/format words."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"캐릭터: {character_desc}\n"
                            f"장면 설명: {content}"
                        ),
                    },
                ],
            },
        )
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"].strip()
        # 20단어 초과 시 잘라냄
        words = raw.split()
        if len(words) > 20:
            raw = " ".join(words[:20]).rstrip(",")
        return raw


async def regenerate_scene_image_task(
    scene_id: str,
    character_desc: str,
    user_id: str,
    progress_callback: Callable[[int, str], Awaitable[None]] | None = None,
) -> None:
    """장면 시작 프레임 재생성 (콘티 설명 기반으로 프롬프트 재생성)"""

    async def notify(pct: int, step: str) -> None:
        if progress_callback:
            await progress_callback(pct, step)

    try:
        scene = await db.storyboardscene.find_unique(
            where={"id": scene_id}
        )
        if not scene:
            raise ValueError("장면을 찾을 수 없습니다")

        await db.storyboardscene.update(
            where={"id": scene_id},
            data={"imageStatus": "GENERATING"},
        )
        await notify(15, "콘티 설명을 분석하고 있습니다...")

        # 현재 content 기반으로 새 imagePrompt 생성
        new_prompt = await content_to_image_prompt(
            scene.content, character_desc
        )
        await notify(35, "이미지 프롬프트 생성 완료")

        await notify(45, "AI가 시작 프레임을 생성하고 있습니다...")
        s3_url = await generate_scene_image(
            new_prompt, character_desc, user_id
        )

        # 이미지 + 새 프롬프트 모두 DB에 저장
        await db.storyboardscene.update(
            where={"id": scene_id},
            data={
                "imageUrl": s3_url,
                "imagePrompt": new_prompt,
                "imageStatus": "COMPLETED",
            },
        )
        await notify(100, "이미지 재생성 완료!")

    except Exception:
        logger.exception("이미지 재생성 실패: %s", scene_id)
        try:
            await db.storyboardscene.update(
                where={"id": scene_id},
                data={"imageStatus": "FAILED"},
            )
        except Exception:
            logger.exception(
                "FAILED 상태 업데이트 실패: %s", scene_id
            )
        if progress_callback:
            await progress_callback(-1, "이미지 생성에 실패했습니다")
