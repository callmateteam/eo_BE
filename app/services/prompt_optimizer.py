"""Hailuo I2V 프롬프트 최적화 엔진 v4

핵심 원칙 (리서치 기반):
1. imagePrompt를 배경 컨텍스트로 직접 사용 (키워드 매칭 제거)
2. motionPrompt를 동작 전용으로만 사용 (imagePrompt fallback 제거)
3. 90단어 이내, 자연스러운 문장 (목록형 금지)
4. 자연스러운 관절/동작 키워드 필수 (로봇 동작 방지)
5. Hailuo [bracket] 카메라 문법 사용
6. 캐릭터 일관성 키워드 필수 삽입
7. anti-text 지시 필수 (영어 텍스트 시각적 렌더링 방지)
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# ── 장면 유형별 자연스러운 동작 보강 키워드 ──

MOTION_ENHANCERS: dict[str, str] = {
    "cooking": (
        "subtle rhythmic arm motion, gentle wrist movement, "
        "minimal body sway, character face and body unchanged"
    ),
    "eating": (
        "subtle hand-to-mouth movement, gentle head nod, "
        "relaxed posture, character appearance preserved"
    ),
    "walking": (
        "gentle walking motion with subtle weight shift, "
        "minimal arm swing, character design preserved"
    ),
    "action": (
        "controlled fluid motion, subtle weight transfer, "
        "character proportions maintained throughout"
    ),
    "sitting": (
        "gentle breathing motion, subtle body sway, "
        "relaxed posture, character appearance unchanged"
    ),
    "talking": (
        "subtle lip movement, gentle head tilt, "
        "minimal hand gestures, character face preserved"
    ),
    "default": (
        "subtle natural motion, gentle movement, "
        "character appearance preserved throughout"
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

_CAMERA_BY_POSITION = {
    "first": "[Truck right] Wide establishing shot",
    "middle": "[Pan left] Medium shot",
    "last": "[Push in] Medium close-up",
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
    """한글이 포함된 world_context를 영어로 변환한다.

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
    """Hailuo I2V 최적화 프롬프트 v4

    v3 → v4 변경:
    - imagePrompt를 배경 컨텍스트로 직접 사용 (키워드 매칭 제거)
    - motionPrompt fallback에서 imagePrompt 제거 (배경과 중복 방지)
    - anti-text 지시 추가 (Hailuo가 영어를 시각적으로 렌더링하는 것 방지)
    - enrichedIdea/world_context는 imagePrompt 없을 때만 폴백
    """
    scene_type = detect_scene_type(scene_content, image_prompt)
    motion_enhancer = MOTION_ENHANCERS.get(scene_type, MOTION_ENHANCERS["default"])

    parts: list[str] = []

    # 1. 카메라 (Hailuo [bracket] 문법 — 반드시 맨 앞)
    if scene_order == 1:
        camera = _CAMERA_BY_POSITION["first"]
    elif scene_order == total_scenes:
        camera = _CAMERA_BY_POSITION["last"]
    else:
        camera = _CAMERA_BY_POSITION["middle"]
    parts.append(camera)

    # 2. 장면 배경/장소 — imagePrompt를 직접 사용 (이미 영어, 30단어 이내)
    #    imagePrompt가 없을 때만 enrichedIdea/world_context 폴백
    if image_prompt:
        parts.append(f"Scene setting: {image_prompt}.")
    elif enriched_background:
        bg_en = _translate_context_to_english(enriched_background)
        if bg_en:
            parts.append(f"In {bg_en}.")
    elif world_context:
        wc_en = _translate_context_to_english(world_context)
        if wc_en:
            parts.append(f"Scene set in {wc_en}.")

    # 3. 분위기/조명 (enrichedIdea.mood → bgm_mood fallback → 조명 매핑)
    lighting = ""
    if enriched_mood:
        mood_key = enriched_mood.lower().split(",")[0].split("/")[0].strip()
        lighting = _MOOD_LIGHTING.get(mood_key, "")
    if not lighting and bgm_mood:
        lighting = _MOOD_LIGHTING.get(bgm_mood.lower(), "")
    if lighting:
        parts.append(f"{lighting}.")

    # 4. 동작 (motionPrompt만 사용 — imagePrompt는 배경에서 이미 사용)
    if motion_prompt:
        parts.append(motion_prompt)

    # 5. 동작 보강 (자연스러운 움직임)
    parts.append(motion_enhancer)

    # 6. 캐릭터 보존 + 품질 + anti-text (반드시 마지막)
    parts.append(
        "Maintain exact character colors, proportions, and design "
        "from reference image throughout the entire clip. "
        "Smooth fluid animation. "
        "NO text, words, letters, signs, or writing visible in the video."
    )

    # 자연스러운 문장형 조합
    prompt = " ".join(p for p in parts if p)

    # 90단어 제한 (짧을수록 캐릭터 보존 우수)
    words = prompt.split()
    if len(words) > 90:
        prompt = " ".join(words[:90])

    logger.info(
        "Hailuo 프롬프트 v4: scene=%d, type=%s, words=%d, "
        "has_motion=%s, has_image_prompt=%s, has_enriched=%s",
        scene_order,
        scene_type,
        len(prompt.split()),
        bool(motion_prompt),
        bool(image_prompt),
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
