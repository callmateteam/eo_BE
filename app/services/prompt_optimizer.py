"""Hailuo I2V 프롬프트 최적화 엔진 v5

핵심 원칙 (리서치 기반):
1. imagePrompt에서 배경만 간략 추출 (_extract_scene_context 사용)
2. motionPrompt를 동작 전용으로만 사용
3. 60단어 이내, 자연스러운 문장 (짧을수록 캐릭터 보존 우수)
4. 자연스러운 관절/동작 키워드 필수 (로봇 동작 방지)
5. [Static shot] 카메라 고정 (캐릭터 보존 최우선)
6. 리서치 검증된 고효과 캐릭터 보존 키워드 사용
7. 부정형 지시 제거 (Hailuo에서 효과 없음, 토큰 낭비)
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# ── 장면 유형별 자연스러운 동작 보강 키워드 ──

MOTION_ENHANCERS: dict[str, str] = {
    "cooking": (
        "Only arms and hands move with gentle stirring motion. "
        "Head, face shape, body shape, colors stay FROZEN."
    ),
    "eating": (
        "Only hands move toward mouth, slight head nod. "
        "Face shape, body shape, colors stay FROZEN."
    ),
    "walking": (
        "Only legs move with small steps, slight arm swing. "
        "Face, body shape, colors stay FROZEN."
    ),
    "action": (
        "Only arms move with controlled motion. "
        "Face shape, body proportions, colors stay FROZEN."
    ),
    "sitting": (
        "Only slight breathing motion, tiny body sway. "
        "Face, body shape, colors stay FROZEN."
    ),
    "talking": (
        "Only mouth moves slightly, gentle head tilt. "
        "Face shape, body shape, colors stay FROZEN."
    ),
    "default": (
        "Only subtle natural idle motion. "
        "Face, body shape, colors stay FROZEN."
    ),
}

# ── 동작 키워드 → 장면 유형 매핑 ──

_ACTION_KEYWORDS: dict[str, str] = {
    "cook": "cooking",
    "요리": "cooking",
    "chop": "cooking",
    "slice": "cooking",
    "stir": "cooking",
    "fry": "cooking",
    "자르": "cooking",
    "썰": "cooking",
    "볶": "cooking",
    "eating": "eating",
    "먹": "eating",
    "drink": "eating",
    "마시": "eating",
    "bite": "eating",
    "chew": "eating",
    "walk": "walking",
    "걷": "walking",
    "run": "walking",
    "뛰": "walking",
    "달리": "walking",
    "산책": "walking",
    "fight": "action",
    "싸우": "action",
    "attack": "action",
    "공격": "action",
    "sword": "action",
    "kick": "action",
    "punch": "action",
    "sit": "sitting",
    "앉": "sitting",
    "study": "sitting",
    "공부": "sitting",
    "read": "sitting",
    "읽": "sitting",
    "talk": "talking",
    "말": "talking",
    "speak": "talking",
    "대화": "talking",
    "chat": "talking",
}

# ── 카메라 앵글 (Hailuo [bracket] 문법) ──
# v5: 캐릭터 보존을 위해 [Static shot] 고정 (리서치: 최고 fidelity)

_CAMERA_BY_POSITION = {
    "first": "[Static shot]",
    "middle": "[Static shot]",
    "last": "[Static shot]",
}

# ── 조명 매핑 ──

_MOOD_LIGHTING: dict[str, str] = {
    "epic": "dramatic golden hour lighting with lens flare",
    "funny": "bright cheerful lighting with vibrant colors",
    "calm": "soft natural lighting with warm tones",
    "tense": "low-key dramatic lighting with deep shadows",
    "sad": "overcast muted lighting with cool blue tones",
    "upbeat": "bright daylight with saturated colors",
    "mysterious": "moody atmospheric lighting with fog",
}

# ── 한글 → 영어 배경/분위기 매핑 (world_context 번역용) ──

_KO_EN_CONTEXT: dict[str, str] = {
    "카페": "cafe",
    "학교": "school",
    "교실": "classroom",
    "공원": "park",
    "숲": "forest",
    "바다": "ocean",
    "해변": "beach",
    "도시": "city",
    "거리": "street",
    "방": "room",
    "집": "house",
    "사무실": "office",
    "병원": "hospital",
    "식당": "restaurant",
    "마을": "village",
    "성": "castle",
    "우주": "space",
    "동굴": "cave",
    "산": "mountain",
    "강": "river",
    "호수": "lake",
    "하늘": "sky",
    "지하": "underground",
    "왕국": "kingdom",
    "세계관": "world",
}


def _translate_context_to_english(text: str) -> str:
    """한글이 포함된 world_context를 영어로 변환한다 (동기, 키워드 매핑만).

    이미 영어면 그대로 반환. 한글 키워드가 있으면 매핑으로 치환.
    매핑에 없는 한글은 그대로 유지 (빈 문자열보다 나음).
    """
    if not text:
        return ""
    # 이미 영어만으로 구성되면 그대로
    has_korean = any("\uac00" <= ch <= "\ud7a3" for ch in text)
    if not has_korean:
        return text
    result = text
    for ko, en in _KO_EN_CONTEXT.items():
        result = result.replace(ko, en)
    return result.strip() or text


async def translate_context_to_english_async(text: str) -> str:
    """한글 배경/분위기를 영어로 번역 (키워드 매핑 → GPT 폴백).

    키워드 매핑으로 먼저 시도하고, 한글이 남아있으면 GPT-4o-mini로 번역.
    """
    import asyncio

    from app.core.config import settings
    from app.core.http_client import get_openai_client

    if not text:
        return ""

    # 1. 기존 키워드 매핑 시도
    result = _translate_context_to_english(text)
    has_korean = any("\uac00" <= ch <= "\ud7a3" for ch in result)
    if not has_korean:
        return result

    # 2. 한글 남아있으면 GPT로 번역
    try:
        client = get_openai_client()
        async with asyncio.timeout(10):
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "gpt-4o-mini",
                    "max_tokens": 50,
                    "temperature": 0,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "Translate the Korean scene/background description "
                                "to English. Max 15 words. Output ONLY the translation."
                            ),
                        },
                        {"role": "user", "content": text},
                    ],
                },
            )
            resp.raise_for_status()
            translated = resp.json()["choices"][0]["message"]["content"].strip()
            logger.info("GPT 배경 번역: %s → %s", text[:30], translated)
            return translated
    except Exception:
        logger.warning("GPT 배경 번역 실패, 키워드 매핑 결과 사용: %s", result[:30])
        return result


def _extract_scene_context(image_prompt: str | None) -> str:
    """imagePrompt에서 배경/장소/분위기 키워드를 추출한다.

    imagePrompt 전체를 넣으면 이미지 내용 반복이 되므로,
    장면 설정(setting) 부분만 뽑아서 자연어 한줄로 반환.
    """
    if not image_prompt:
        return ""
    # imagePrompt의 앞부분이 보통 장소/배경 묘사
    # "A cozy cafe interior with warm lighting, character sitting..."
    # → "A cozy cafe interior with warm lighting" 까지만 추출
    setting_keywords = {
        "interior", "exterior", "indoor", "outdoor", "room", "cafe",
        "street", "park", "forest", "beach", "ocean", "mountain",
        "city", "village", "castle", "school", "office", "kitchen",
        "garden", "rooftop", "bridge", "temple", "shrine", "alley",
        "market", "shop", "store", "library", "station", "hospital",
        "church", "palace", "cave", "lake", "river", "field",
        "arena", "stage", "courtyard", "hallway", "bedroom",
        "restaurant", "bar", "night", "sunset", "sunrise", "dawn",
        "rain", "snow", "fog", "cloudy", "sunny", "moonlight",
        "warm lighting", "dim lighting", "bright", "cozy", "dark",
    }
    prompt_lower = image_prompt.lower()
    # 장소/배경 키워드가 하나라도 있으면 imagePrompt에서 배경 부분 추출
    has_setting = any(kw in prompt_lower for kw in setting_keywords)
    if not has_setting:
        return ""
    # 첫 번째 콤마 절까지가 보통 배경 묘사 (최대 2절)
    segments = image_prompt.split(",")
    context_parts = []
    for seg in segments[:3]:
        seg_lower = seg.strip().lower()
        if any(kw in seg_lower for kw in setting_keywords):
            context_parts.append(seg.strip())
    return ", ".join(context_parts) if context_parts else ""


def detect_scene_type(scene_content: str, image_prompt: str | None = None) -> str:
    """장면 내용에서 동작 유형 자동 감지"""
    text = f"{scene_content} {image_prompt or ''}".lower()
    for keyword, scene_type in _ACTION_KEYWORDS.items():
        if keyword in text:
            return scene_type
    return "default"


def select_best_image(
    extra_images: str,
    scene_type: str,
    base_image_url: str,
) -> str:
    """장면 유형에 맞는 최적 S3 이미지 자동 선택"""
    if not extra_images:
        return base_image_url

    images = [img.strip() for img in extra_images.split(",") if img.strip()]
    base_dir = base_image_url.rsplit("/", 1)[0]

    preferred: dict[str, list[str]] = {
        "cooking": ["cooking", "fullbody", "action", "side"],
        "eating": ["eating", "face", "side"],
        "walking": ["fullbody", "walking", "side", "action"],
        "action": ["action", "fullbody", "side"],
        "sitting": ["sitting", "face", "fullbody", "side"],
        "talking": ["face", "talking", "fullbody", "side"],
        "default": ["fullbody", "face", "side"],
    }

    pref_list = preferred.get(scene_type, preferred["default"])

    for pref in pref_list:
        for img in images:
            if pref in img.lower():
                return f"{base_dir}/{img}"

    if images:
        return f"{base_dir}/{images[0]}"
    return base_image_url


def build_hailuo_prompt(
    *,
    scene_content: str,
    image_prompt: str | None = None,
    motion_prompt: str | None = None,
    character_name: str = "",
    world_context: str = "",
    art_style: str = "",
    series_description: str = "",
    secondary_character: str = "",
    secondary_character_desc: str = "",
    bgm_mood: str | None = None,
    enriched_background: str = "",
    enriched_mood: str = "",
    scene_order: int = 1,
    total_scenes: int = 1,
    duration: int = 5,
) -> dict:
    """Hailuo I2V 최적화 프롬프트 v5

    v4 → v5 변경 (리서치 기반):
    - 카메라: 모든 씬 [Static shot] 고정 (캐릭터 보존 최우선)
    - 캐릭터 보존: "CRITICAL:..." → 리서치 고효과 키워드로 교체
    - 배경: imagePrompt 전체 삽입 → _extract_scene_context()로 1~2절만
    - 부정형 제거: "Do NOT...", "NO text..." 삭제 (Hailuo에서 효과 없음)
    - 단어 제한: 90 → 60 (짧을수록 캐릭터 보존 우수)
    """
    scene_type = detect_scene_type(scene_content, image_prompt)
    motion_enhancer = MOTION_ENHANCERS.get(scene_type, MOTION_ENHANCERS["default"])

    parts: list[str] = []

    # 1. 카메라 ([Static shot] 고정 — 캐릭터 보존 최우선)
    parts.append("[Static shot]")

    # 2. 리서치 검증된 캐릭터 보존 키워드 (고효과, 반드시 카메라 직후)
    parts.append(
        "Preserve exact character colors and design from reference image."
    )

    # 3. 장면 배경/장소 — _extract_scene_context로 간략 추출
    bg_context = _extract_scene_context(image_prompt) if image_prompt else ""
    if bg_context:
        parts.append(f"{bg_context}.")
    elif enriched_background:
        bg_en = _translate_context_to_english(enriched_background)
        if bg_en:
            parts.append(f"In {bg_en}.")
    elif world_context:
        wc_en = _translate_context_to_english(world_context)
        if wc_en:
            parts.append(f"In {wc_en}.")

    # 4. 분위기/조명 (enrichedIdea.mood → bgm_mood fallback)
    lighting = ""
    if enriched_mood:
        mood_key = enriched_mood.lower().split(",")[0].split("/")[0].strip()
        lighting = _MOOD_LIGHTING.get(mood_key, "")
    if not lighting and bgm_mood:
        lighting = _MOOD_LIGHTING.get(bgm_mood.lower(), "")
    if lighting:
        parts.append(f"{lighting}.")

    # 5. 동작 (motionPrompt만 사용)
    if motion_prompt:
        parts.append(motion_prompt)

    # 6. 동작 보강 (자연스러운 움직임 + FROZEN 키워드)
    parts.append(motion_enhancer)

    # 7. 품질 마무리 (리서치 고효과 키워드)
    parts.append(
        "Smooth fluid animation, consistent character appearance."
    )

    # 자연스러운 문장형 조합
    prompt = " ".join(p for p in parts if p)

    # 60단어 제한 (짧을수록 캐릭터 보존 우수 — v4 90 → v5 60)
    words = prompt.split()
    if len(words) > 60:
        prompt = " ".join(words[:60])

    logger.info(
        "Hailuo 프롬프트 v5: scene=%d, type=%s, words=%d, "
        "has_motion=%s, bg_context='%s', has_enriched=%s",
        scene_order,
        scene_type,
        len(prompt.split()),
        bool(motion_prompt),
        bg_context[:50] if bg_context else "",
        bool(enriched_background or enriched_mood),
    )

    return {
        "prompt": prompt,
        "_scene_type": scene_type,
    }


# 하위 호환
build_pika_prompt = build_hailuo_prompt


def build_pika_negative_prompt() -> str:
    """Pika v2.2 negative prompt (P19 수정)"""
    return (
        "blurry, low resolution, distorted, extra fingers, missing fingers, "
        "bad anatomy, morphing, deformation, face change, proportion change, "
        "shaky camera, text, letters, words, watermark, signature, "
        "3d render, realistic, photorealistic"
    )
