"""커스텀 캐릭터 생성 서비스 - S3 업로드 + GPT-4o Vision 분석"""

from __future__ import annotations

import asyncio
import base64
import json as json_mod
import logging
from collections.abc import Awaitable, Callable

import httpx

from app.core.config import settings
from app.core.database import db
from app.core.s3 import upload_image
from app.schemas.custom_character import STYLE_PROMPT, CharacterStyle

logger = logging.getLogger(__name__)

# GPT-4o Vision 시스템 프롬프트
SYSTEM_PROMPT = """\
Character expert for AI video+voice generation.
Analyze images and description, output JSON with two fields.

Rules:
- Output ONLY valid JSON: {"veoPrompt":"...","voiceStyle":"..."}
- veoPrompt: max 60 words, English, comma-separated phrases.
  MUST include ALL of these for character consistency:
  (1) height/build, (2) hair color+style+length,
  (3) eye color+shape, (4) skin tone,
  (5) outfit/clothing details, (6) distinctive marks/accessories,
  (7) body proportions. No style/ratio words.
- voiceStyle: max 25 words, English, TTS voice instruction
  tone, pitch, energy, Korean speaking style for this character

Example:
{"veoPrompt":"170cm slim young woman, waist-length silver hair with side bangs, \
sharp red eyes, fair skin, fitted black leather coat over white blouse, \
silver necklace, slender build with long legs",\
"voiceStyle":"Cool confident young woman, speaks Korean with elegant authority"}"""


def _truncate_prompt(text: str, max_words: int = 60) -> str:
    """veoPrompt를 max_words 이하로 잘라냄"""
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]).rstrip(",")


async def analyze_images_with_gpt(
    image_data_1: bytes,
    image_data_2: bytes,
    name: str,
    description: str,
    style: str,
    content_type_1: str,
    content_type_2: str,
) -> tuple[str, str]:
    """GPT-4o Vision으로 이미지 분석 → (veoPrompt, voiceStyle) 생성"""
    b64_1 = base64.b64encode(image_data_1).decode()
    b64_2 = base64.b64encode(image_data_2).decode()

    media_1 = content_type_1 if content_type_1.startswith("image/") else "image/png"
    media_2 = content_type_2 if content_type_2.startswith("image/") else "image/png"

    # 스타일 프롬프트 힌트 추가
    style_enum = CharacterStyle(style)
    style_hint = STYLE_PROMPT.get(style_enum, "")

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "gpt-4o",
                "max_tokens": 250,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": (
                                    f"Character name: {name}\n"
                                    f"User description: {description}\n"
                                    f"Target style: {style_hint}\n\n"
                                    "Analyze both images and generate "
                                    "veoPrompt + voiceStyle JSON."
                                ),
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{media_1};base64,{b64_1}",
                                    "detail": "auto",
                                },
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{media_2};base64,{b64_2}",
                                    "detail": "auto",
                                },
                            },
                        ],
                    },
                ],
            },
        )
        resp.raise_for_status()
        data = resp.json()
        raw = data["choices"][0]["message"]["content"].strip()
        parsed = json_mod.loads(raw)
        veo_prompt = _truncate_prompt(str(parsed.get("veoPrompt", "")))
        voice_style = str(parsed.get("voiceStyle", ""))[:500]
        return veo_prompt, voice_style


async def process_custom_character(
    character_id: str,
    user_id: str,
    name: str,
    description: str,
    style: str,
    image_data_1: bytes,
    image_data_2: bytes,
    content_type_1: str,
    content_type_2: str,
    progress_callback: Callable[[int, str], Awaitable[None]] | None = None,
) -> None:
    """커스텀 캐릭터 생성 전체 파이프라인 (백그라운드)"""

    async def notify(pct: int, step: str) -> None:
        if progress_callback:
            await progress_callback(pct, step)

    try:
        # Step 1: S3 업로드 (0-30%)
        await notify(10, "이미지 업로드 중...")
        url1 = await asyncio.to_thread(
            upload_image, image_data_1, user_id, content_type=content_type_1
        )
        await notify(20, "이미지 업로드 중...")
        url2 = await asyncio.to_thread(
            upload_image, image_data_2, user_id, content_type=content_type_2
        )
        await notify(30, "이미지 업로드 완료")

        # DB에 이미지 URL 업데이트
        await db.customcharacter.update(
            where={"id": character_id},
            data={"imageUrl1": url1, "imageUrl2": url2},
        )

        # Step 2: GPT-4o Vision 분석 (30-80%)
        await notify(40, "AI 캐릭터 분석 중...")
        veo_prompt, voice_style = await analyze_images_with_gpt(
            image_data_1,
            image_data_2,
            name,
            description,
            style,
            content_type_1,
            content_type_2,
        )
        await notify(80, "프롬프트 생성 완료")

        # Step 3: DB 저장 (80-100%)
        await notify(90, "캐릭터 저장 중...")
        await db.customcharacter.update(
            where={"id": character_id},
            data={
                "veoPrompt": veo_prompt,
                "voiceStyle": voice_style,
                "status": "COMPLETED",
            },
        )
        await notify(100, "캐릭터 생성 완료!")

    except Exception as e:
        logger.exception("커스텀 캐릭터 생성 실패: %s", character_id)
        try:
            await db.customcharacter.update(
                where={"id": character_id},
                data={
                    "status": "FAILED",
                    "errorMsg": str(e)[:500],
                },
            )
        except Exception:
            logger.exception("FAILED 상태 업데이트 실패: %s", character_id)
        if progress_callback:
            await progress_callback(-1, "캐릭터 생성에 실패했습니다")


async def get_custom_characters(user_id: str) -> list[dict]:
    """사용자의 커스텀 캐릭터 목록 조회"""
    chars = await db.customcharacter.find_many(
        where={"userId": user_id},
        order={"createdAt": "desc"},
        take=50,
    )
    return [_to_dict(c) for c in chars]


async def get_custom_character_by_id(character_id: str, user_id: str) -> dict | None:
    """커스텀 캐릭터 단건 조회 (본인 소유만)"""
    c = await db.customcharacter.find_first(where={"id": character_id, "userId": user_id})
    if not c:
        return None
    return _to_dict(c)


async def create_custom_character_record(
    name: str,
    description: str,
    style: str,
    voice_id: str,
    user_id: str,
) -> dict:
    """DB에 PROCESSING 상태로 커스텀 캐릭터 레코드 생성"""
    record = await db.customcharacter.create(
        data={
            "name": name,
            "description": description,
            "style": style,
            "voiceId": voice_id,
            "imageUrl1": "",
            "imageUrl2": "",
            "userId": user_id,
        }
    )
    return {"id": record.id}


async def delete_custom_character(character_id: str, user_id: str) -> None:
    """커스텀 캐릭터 삭제 (소유권 확인 + 스토리보드 연결 확인)"""
    record = await db.customcharacter.find_first(
        where={"id": character_id, "userId": user_id},
    )
    if not record:
        raise ValueError("캐릭터를 찾을 수 없습니다")

    linked = await db.storyboard.count(where={"customCharacterId": character_id})
    if linked > 0:
        raise ValueError("이 캐릭터를 사용하는 콘티가 있어 삭제할 수 없습니다")

    await db.customcharacter.delete(where={"id": character_id})


async def get_custom_character_status(character_id: str, user_id: str) -> dict | None:
    """WS용 커스텀 캐릭터 상태 조회"""
    record = await db.customcharacter.find_first(
        where={"id": character_id, "userId": user_id},
    )
    if not record:
        return None
    return {
        "id": record.id,
        "status": record.status,
    }


def _to_dict(c: object) -> dict:
    """커스텀 캐릭터 모델 → dict 변환"""
    from app.schemas.custom_character import STYLE_LABEL

    style = CharacterStyle(c.style)
    return {
        "id": c.id,
        "name": c.name,
        "description": c.description,
        "style": c.style,
        "style_label": STYLE_LABEL.get(style, ""),
        "image_url_1": c.imageUrl1,
        "image_url_2": c.imageUrl2,
        "veo_prompt": c.veoPrompt,
        "voice_id": c.voiceId,
        "voice_style": c.voiceStyle,
        "status": c.status,
        "error_msg": c.errorMsg,
        "created_at": c.createdAt.isoformat(),
    }
