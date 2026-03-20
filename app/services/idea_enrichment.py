"""아이디어 구체화 서비스 - GPT로 자연어 아이디어를 구조화"""

from __future__ import annotations

import asyncio
import json
import logging

from app.core.config import settings
from app.core.http_client import get_openai_client

logger = logging.getLogger(__name__)

ENRICHMENT_SYSTEM = """\
You are a creative director for short-form video production.
The user gives a raw idea in Korean, along with their selected main character info.
Your job is to enrich and structure the idea into a detailed creative brief
that will be used to generate storyboard scenes.

IMPORTANT: The main character is ALREADY SELECTED by the user.
Do NOT re-describe the character's appearance. Instead, describe their
ACTION, EXPRESSION, EMOTION, and ROLE in this specific video.

Output ONLY valid JSON with these fields:
{{
  "background": "배경 설명 (장소, 시간대, 날씨, 분위기적 배경 요소) - 한글, 2-3문장",
  "mood": "분위기/톤 (감정, 조명, 색감, 전체적인 느낌) - 한글, 1-2문장",
  "main_character": "이 영상에서 메인 캐릭터의 행동, 표정, 감정, 역할 - 한글, 2-3문장. \
외형/복장은 이미 정해져 있으므로 쓰지 마세요. 행동과 감정만 작성.",
  "supporting_characters": ["보조 캐릭터1: 이름 - 외형 묘사 + 행동/역할", "보조 캐릭터2..."],
  "story": "스토리 요약 (도입 → 전개 → 클라이맥스 → 결말) - 한글, 4-6문장"
}}

Rules:
- Write ALL content in Korean
- Be creative but stay faithful to the user's original idea
- main_character field: ONLY actions, expressions, emotions, role in the scene. \
NEVER describe appearance (face, body, color, outfit) — that's already defined.
- supporting_characters: For each one, include both visual description AND \
their role/action in the scene. Use format "이름 - 외형 + 행동".
- supporting_characters can be empty [] if none are mentioned
- story should be structured as a clear narrative arc
- background should be vivid and specific enough to generate consistent images
- mood should describe the emotional tone AND visual style (lighting, colors)
"""

ENRICHMENT_USER = """\
메인 캐릭터 이름: {character_name}
메인 캐릭터 설명: {character_desc}
아이디어: {idea}

위 아이디어를 영상 제작용 크리에이티브 브리프로 구체화해주세요.
메인 캐릭터의 외형은 위에 이미 정의되어 있으니 다시 쓰지 마세요."""


async def enrich_idea(
    idea: str,
    *,
    character_name: str = "",
    character_desc: str = "",
) -> dict:
    """자연어 아이디어를 GPT로 구조화한다.

    Args:
        idea: 사용자 자연어 아이디어
        character_name: 선택된 캐릭터 이름
        character_desc: 선택된 캐릭터 외형 설명

    Returns:
        dict with keys: background, mood, main_character, supporting_characters, story

    Raises:
        ValueError: GPT 응답 파싱 실패 시
    """
    client = get_openai_client()
    max_retries = 3
    last_error: Exception | None = None

    for attempt in range(1, max_retries + 1):
        try:
            async with asyncio.timeout(30):
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
                            {"role": "system", "content": ENRICHMENT_SYSTEM},
                            {
                                "role": "user",
                                "content": ENRICHMENT_USER.format(
                                    idea=idea,
                                    character_name=character_name or "미지정",
                                    character_desc=character_desc or "미지정",
                                ),
                            },
                        ],
                    },
                )
                resp.raise_for_status()
                raw = resp.json()["choices"][0]["message"]["content"].strip()
                logger.debug("GPT 아이디어 구체화 응답 (시도 %d): %s", attempt, raw[:300])
                parsed = json.loads(raw)

                # 필수 필드 검증
                required = {"background", "mood", "main_character", "story"}
                missing = required - set(parsed.keys())
                if missing:
                    logger.warning("GPT 응답 필드 누락 (시도 %d): %s", attempt, missing)
                    last_error = ValueError(f"응답 필드 누락: {missing}")
                    continue

                # 정규화
                result = {
                    "background": str(parsed["background"])[:500],
                    "mood": str(parsed["mood"])[:200],
                    "main_character": str(parsed["main_character"])[:500],
                    "supporting_characters": [
                        str(c)[:300] for c in (parsed.get("supporting_characters") or [])
                    ],
                    "story": str(parsed["story"])[:2000],
                }
                return result

        except Exception as exc:
            logger.warning("GPT 아이디어 구체화 에러 (시도 %d/%d): %s", attempt, max_retries, exc)
            last_error = exc
            if attempt < max_retries:
                await asyncio.sleep(1)

    raise last_error or ValueError("아이디어 구체화 실패")
