"""TTS 서비스 - OpenAI gpt-4o-mini-tts를 사용한 캐릭터 음성 생성"""

from __future__ import annotations

import asyncio
import logging

import httpx

from app.core.config import settings
from app.core.s3 import upload_image

logger = logging.getLogger(__name__)

# TTS 동시 요청 제한
_TTS_SEMAPHORE: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
    """이벤트 루프 시작 후 세마포어 지연 생성"""
    global _TTS_SEMAPHORE  # noqa: PLW0603
    if _TTS_SEMAPHORE is None:
        _TTS_SEMAPHORE = asyncio.Semaphore(5)
    return _TTS_SEMAPHORE


# OpenAI TTS 지원 음성 목록
VALID_VOICES = {
    "alloy",
    "ash",
    "ballad",
    "coral",
    "echo",
    "fable",
    "onyx",
    "nova",
    "sage",
    "shimmer",
}


async def generate_tts(
    text: str,
    voice_id: str,
    voice_style: str,
    user_id: str,
    *,
    narration_style: str = "character",
) -> str:
    """OpenAI TTS로 음성 생성 → S3 업로드 → URL 반환

    Args:
        text: 읽을 텍스트 (한국어)
        voice_id: OpenAI TTS 음성 ID (alloy, echo 등)
        voice_style: 캐릭터 음성 스타일 지시 (instructions 파라미터)
        user_id: S3 업로드용 유저 ID
        narration_style: "character" 또는 "narrator"

    Returns:
        S3 URL of the generated audio file
    """
    if voice_id not in VALID_VOICES:
        voice_id = "nova"

    # narration_style에 따라 instructions 구성
    if narration_style == "narrator":
        instructions = (
            "Warm, engaging Korean narrator voice. "
            "Slightly upbeat and expressive like a popular YouTube storyteller. "
            "Natural pacing with subtle emotional emphasis."
        )
    elif voice_style:
        instructions = voice_style
    else:
        instructions = (
            "Expressive Korean speech with natural emotion. "
            "Lively and engaging tone, like narrating an anime story."
        )

    async with _get_semaphore():
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                "https://api.openai.com/v1/audio/speech",
                headers={
                    "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "gpt-4o-mini-tts",
                    "input": text,
                    "voice": voice_id,
                    "instructions": instructions,
                    "response_format": "mp3",
                },
            )
            resp.raise_for_status()
            audio_bytes = resp.content

    # S3 업로드
    s3_url = await asyncio.to_thread(
        upload_image,
        audio_bytes,
        user_id,
        content_type="audio/mpeg",
        folder="storyboard-narration",
    )
    return s3_url


async def generate_scene_narrations(
    scenes: list,
    voice_id: str,
    voice_style: str,
    user_id: str,
) -> None:
    """DB에 저장된 장면 목록을 받아 narration이 있는 장면에 TTS 생성

    각 장면의 narration 필드가 있고 narrationStyle이 none이 아닌 경우
    TTS를 생성하여 narrationUrl을 DB에 저장합니다.
    """
    from app.core.database import db

    tasks = []
    for scene in scenes:
        if not scene.narration or scene.narrationStyle == "none":
            continue

        async def _gen_tts(sc: object) -> None:
            try:
                url = await generate_tts(
                    text=sc.narration,
                    voice_id=voice_id,
                    voice_style=voice_style,
                    user_id=user_id,
                    narration_style=sc.narrationStyle,
                )
                await db.storyboardscene.update(
                    where={"id": sc.id},
                    data={"narrationUrl": url},
                )
                logger.info("TTS 생성 완료: scene=%s", sc.id)
            except Exception:
                logger.exception("TTS 생성 실패: scene=%s", sc.id)

        tasks.append(_gen_tts(scene))

    if tasks:
        await asyncio.gather(*tasks)
