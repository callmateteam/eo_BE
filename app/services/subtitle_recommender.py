"""GPT 기반 씬별 자막 스타일 자동 추천

씬 내용, 나레이션 텍스트, BGM 분위기를 분석하여
각 장면에 최적의 자막 스타일(애니메이션, 색상, 폰트 등)을 추천한다.
"""

from __future__ import annotations

import asyncio
import json
import logging

from app.core.config import settings
from app.schemas.video_edit import (
    BackgroundStyle,
    ShadowStyle,
    SubtitleAnimation,
    SubtitleFont,
    SubtitleStyle,
)

logger = logging.getLogger(__name__)

SUBTITLE_STYLE_SYSTEM = """\
You are a professional short-form video subtitle designer for anime content.
Analyze each scene's mood, narration, and context to recommend the perfect subtitle style.

Available options:
- font: "Pretendard" (modern/clean), "GmarketSans" (bold/impactful), \
"DoHyeon" (fun/casual), "NanumSquareRound" (soft/cute), \
"NanumMyeongjo" (elegant/serious), "MapoFlowerIsland" (handwritten/warm), \
"NanumGothic" (neutral), "NanumBarunGothic" (readable)
- animation: "popup" (energetic/surprise), "bounce" (fun/playful), \
"glow" (dramatic/emotional), "slide_up" (calm/narrative), \
"fadein" (gentle/serious), "typing" (suspense/reveal), "none" (neutral)
- color: hex color for text (ensure contrast with anime backgrounds)
- font_size: 28-48 (bigger=more impact, smaller=more subtle)
- outline_size: 2-6 (thicker=more visible)
- outline_color: hex (usually dark for contrast)
- bold: true/false

Style guidelines:
- Action/exciting scenes → popup/bounce, GmarketSans, larger font, bright colors
- Emotional/sad scenes → glow/fadein, NanumMyeongjo, softer colors (#E0E0FF)
- Funny/casual scenes → bounce/popup, DoHyeon, playful colors (#FFFF00, #FF69B4)
- Calm/narrative scenes → slide_up/fadein, Pretendard, white
- Dramatic reveals → glow/typing, GmarketSans, gold (#FFD700)
- Inner thoughts → fadein, slightly transparent
- Short exclamations → popup with big font

Also generate short, trendy subtitle TEXT for each scene.
- Subtitle text is NOT the same as narration.
- Subtitle should be short (1-8 words), punchy, expressive.
- Use 2024-2025 Korean short-form trends: 상황 설명, 리액션, 짧은 감탄.
- Examples: "이게 된다고?", "참을 수 없는 맛", "결국 터졌다", \
"진짜 실화냐", "이 조합 미쳤다", "아 이건 좀..", "ㄹㅇ 레전드"
- Avoid outdated expressions like "헐 대박", "OMG".
- Match the scene mood and action.

Output ONLY a JSON array matching the number of scenes. Each element:
{"font":"...","animation":"...","color":"#...","font_size":36,\
"outline_size":4,"outline_color":"#000000","bold":true,\
"text":"짧은 자막 텍스트"}"""


async def recommend_subtitle_styles(
    scenes: list[dict],
    bgm_mood: str | None = None,
    character_name: str = "",
) -> list[SubtitleStyle]:
    """GPT로 씬별 자막 스타일 일괄 추천

    Args:
        scenes: generate_scenes_with_gpt()에서 반환된 장면 목록
        bgm_mood: 전체 BGM 분위기
        character_name: 캐릭터 이름 (컨텍스트용)

    Returns:
        씬 수와 동일한 길이의 SubtitleStyle 리스트
    """
    # 나레이션 없는 씬은 기본 스타일
    narrated = [
        (i, s) for i, s in enumerate(scenes)
        if s.get("narration") and s.get("narrationStyle", "none") != "none"
    ]

    if not narrated:
        return [_default_style() for _ in scenes]

    # GPT 요청용 씬 요약
    scene_summaries = []
    for idx, (i, s) in enumerate(narrated):
        scene_summaries.append({
            "scene_number": idx + 1,
            "content": s.get("content", "")[:200],
            "narration": s.get("narration", "")[:200],
            "narration_style": s.get("narrationStyle", "character"),
            "duration": s.get("duration", 5.0),
        })

    user_prompt = (
        f"캐릭터: {character_name or '주인공'}\n"
        f"BGM 분위기: {bgm_mood or '없음'}\n"
        f"총 {len(narrated)}개 씬의 자막 스타일을 추천해주세요.\n\n"
        f"씬 정보:\n{json.dumps(scene_summaries, ensure_ascii=False, indent=2)}"
    )

    try:
        import httpx

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "gpt-4o-mini",
                    "max_tokens": 1000,
                    "temperature": 0.6,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": SUBTITLE_STYLE_SYSTEM},
                        {"role": "user", "content": user_prompt},
                    ],
                },
            )
            resp.raise_for_status()
            raw = resp.json()["choices"][0]["message"]["content"].strip()
            parsed = json.loads(raw)

            # 배열 추출
            if isinstance(parsed, list):
                recs = parsed
            else:
                for key in ("styles", "subtitles", "recommendations", "data"):
                    if key in parsed and isinstance(parsed[key], list):
                        recs = parsed[key]
                        break
                else:
                    recs = []

    except Exception:
        logger.warning("자막 스타일 GPT 추천 실패, 기본값 사용")
        recs = []

    # 결과를 SubtitleStyle + 텍스트로 변환
    results: list[SubtitleStyle] = [_default_style() for _ in scenes]
    texts: list[str | None] = [None] * len(scenes)

    for idx, (scene_idx, _) in enumerate(narrated):
        if idx < len(recs):
            results[scene_idx] = _parse_recommendation(recs[idx])
            texts[scene_idx] = recs[idx].get("text")
        else:
            results[scene_idx] = _default_style()

    logger.info(
        "자막 스타일 추천 완료: %d/%d 씬",
        min(len(recs), len(narrated)),
        len(narrated),
    )
    return results, texts


def _parse_recommendation(rec: dict) -> SubtitleStyle:
    """GPT 추천 결과를 SubtitleStyle로 변환"""
    font_map = {
        "Pretendard": SubtitleFont.PRETENDARD,
        "GmarketSans": SubtitleFont.GMARKET_SANS,
        "DoHyeon": SubtitleFont.DOHYEON,
        "NanumSquareRound": SubtitleFont.NANUM_SQUARE_ROUND,
        "NanumMyeongjo": SubtitleFont.NANUM_MYEONGJO,
        "MapoFlowerIsland": SubtitleFont.MAPO_FLOWER,
        "NanumGothic": SubtitleFont.NANUM_GOTHIC,
        "NanumBarunGothic": SubtitleFont.NANUM_BARUN_GOTHIC,
    }

    anim_map = {
        "popup": SubtitleAnimation.POPUP,
        "bounce": SubtitleAnimation.BOUNCE,
        "glow": SubtitleAnimation.GLOW,
        "slide_up": SubtitleAnimation.SLIDE_UP,
        "fadein": SubtitleAnimation.FADEIN,
        "typing": SubtitleAnimation.TYPING,
        "none": SubtitleAnimation.NONE,
    }

    font = font_map.get(rec.get("font", ""), SubtitleFont.PRETENDARD)
    animation = anim_map.get(rec.get("animation", ""), SubtitleAnimation.POPUP)
    color = rec.get("color", "#FFFFFF")
    font_size = max(12, min(72, int(rec.get("font_size", 36))))
    outline_size = max(0, min(8, int(rec.get("outline_size", 4))))
    outline_color = rec.get("outline_color", "#000000")
    bold = bool(rec.get("bold", True))

    return SubtitleStyle(
        font=font,
        font_size=font_size,
        color=color,
        bold=bold,
        shadow=ShadowStyle(enabled=True, color="#000000", offset=3),
        background=BackgroundStyle(enabled=False),
        outline_color=outline_color,
        outline_size=outline_size,
        animation=animation,
    )


def _default_style() -> SubtitleStyle:
    """기본 자막 스타일"""
    return SubtitleStyle(
        font=SubtitleFont.PRETENDARD,
        font_size=36,
        color="#FFFFFF",
        bold=True,
        shadow=ShadowStyle(enabled=True, color="#000000", offset=3),
        background=BackgroundStyle(enabled=False),
        outline_color="#000000",
        outline_size=4,
        animation=SubtitleAnimation.POPUP,
    )
