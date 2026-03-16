"""Pika v2.2 프롬프트 최적화 엔진

S3 캐릭터 이미지 + 시드 데이터 → Pika image-to-video 최적 프롬프트 자동 생성.
GPT가 사용자 아이디어를 Pika 최적화 프롬프트로 변환하는 시스템.

핵심 규칙:
1. 이미지에 있는 것은 반복하지 않음 (동작/배경만 명시)
2. 80-120 단어 이내
3. 동작 1-2개만 (한 프롬프트에 너무 많은 행동 금지)
4. negative prompt로 손/변형 방지
5. 배경을 첫 문장에 명시
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# ── Pika 파라미터 프리셋 (장면 유형별) ──

PIKA_PRESETS: dict[str, dict] = {
    "cooking": {
        "guidance_scale": 16,
        "motion": 1.5,
        "negative": (
            "deformed hands, extra fingers, warped hands, "
            "distorted knife, melting food, jitter, flicker, "
            "morphing, text, letters, 3D render"
        ),
    },
    "eating": {
        "guidance_scale": 16,
        "motion": 1.5,
        "negative": (
            "deformed hands, extra fingers, warped face, "
            "unnatural mouth, food distortion, jitter, flicker, "
            "morphing, text, letters, 3D render"
        ),
    },
    "walking": {
        "guidance_scale": 15,
        "motion": 2.0,
        "negative": (
            "unnatural gait, floating feet, jitter, flicker, "
            "morphing, extra limbs, text, letters, 3D render"
        ),
    },
    "action": {
        "guidance_scale": 15,
        "motion": 3.0,
        "negative": (
            "warped weapons, extra limbs, unnatural physics, "
            "jitter, flicker, morphing, text, letters, 3D render"
        ),
    },
    "sitting": {
        "guidance_scale": 16,
        "motion": 1.0,
        "negative": (
            "unnatural posture, deformed hands, warped face, "
            "jitter, flicker, morphing, text, letters, 3D render"
        ),
    },
    "talking": {
        "guidance_scale": 14,
        "motion": 1.0,
        "negative": (
            "unnatural lip movement, warped face, off-model, "
            "jitter, flicker, morphing, text, letters, 3D render"
        ),
    },
    "default": {
        "guidance_scale": 16,
        "motion": 1.5,
        "negative": (
            "deformed hands, extra fingers, warped face, "
            "off-model, jitter, flicker, morphing, "
            "text, letters, watermark, 3D render"
        ),
    },
}

# ── 동작 키워드 → 프리셋 매핑 ──

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
    "eat": "eating",
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

# ── 카메라 앵글 (장면 위치 기반) ──

_CAMERA_BY_POSITION = {
    "first": "Wide establishing shot, gentle camera drift right",
    "middle": "Medium shot, subtle camera pan",
    "last": "Medium close-up, slow push in",
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


def detect_scene_type(scene_content: str, image_prompt: str | None = None) -> str:
    """장면 내용에서 동작 유형 자동 감지"""
    text = f"{scene_content} {image_prompt or ''}".lower()
    for keyword, scene_type in _ACTION_KEYWORDS.items():
        if keyword in text:
            return scene_type
    return "default"


def get_pika_preset(scene_type: str) -> dict:
    """장면 유형에 맞는 Pika 파라미터 프리셋 반환"""
    return PIKA_PRESETS.get(scene_type, PIKA_PRESETS["default"])


def select_best_image(
    extra_images: str,
    scene_type: str,
    base_image_url: str,
) -> str:
    """장면 유형에 맞는 최적 S3 이미지 자동 선택

    Args:
        extra_images: 콤마 구분 추가 이미지 파일명 (예: "fullbody.jpg,eating.jpg,side.png")
        scene_type: 감지된 장면 유형
        base_image_url: 캐릭터 기본 이미지 URL (예: https://.../characters/monkey-d-luffy/image.png)

    Returns:
        가장 적합한 S3 이미지 URL
    """
    if not extra_images:
        return base_image_url

    images = [img.strip() for img in extra_images.split(",") if img.strip()]
    base_dir = base_image_url.rsplit("/", 1)[0]  # .../characters/monkey-d-luffy

    # 장면 유형별 선호 이미지 매핑
    preferred: dict[str, list[str]] = {
        "cooking": ["fullbody", "action", "side"],
        "eating": ["eating", "face", "side"],
        "walking": ["fullbody", "side", "action"],
        "action": ["action", "fullbody", "side"],
        "sitting": ["face", "fullbody", "side"],
        "talking": ["face", "fullbody", "side"],
        "default": ["fullbody", "face", "side"],
    }

    pref_list = preferred.get(scene_type, preferred["default"])

    for pref in pref_list:
        for img in images:
            if pref in img.lower():
                return f"{base_dir}/{img}"

    # 매칭 없으면 첫 번째 추가 이미지 또는 기본 이미지
    if images:
        return f"{base_dir}/{images[0]}"
    return base_image_url


def build_pika_prompt(
    *,
    scene_content: str,
    image_prompt: str | None = None,
    character_name: str = "",
    world_context: str = "",
    art_style: str = "",
    bgm_mood: str | None = None,
    scene_order: int = 1,
    total_scenes: int = 1,
    duration: int = 5,
) -> dict:
    """Pika v2.2 image-to-video 최적화 프롬프트 생성

    Returns:
        {
            "prompt": str,
            "negative_prompt": str,
            "guidance_scale": float,
            "motion": float,
        }
    """
    scene_type = detect_scene_type(scene_content, image_prompt)
    preset = get_pika_preset(scene_type)

    parts: list[str] = []

    # 1. 배경/세계관 (첫 문장에 - 흰 배경 방지)
    if world_context:
        # 세계관에서 배경 키워드 추출
        parts.append(f"In {world_context.split(',')[0].strip()}")

    # 2. 동작 (이미지에 있는 것은 반복하지 않음 - 동작만)
    if image_prompt:
        parts.append(image_prompt)
    else:
        parts.append(scene_content)

    # 3. 카메라
    if scene_order == 1:
        camera = _CAMERA_BY_POSITION["first"]
    elif scene_order == total_scenes:
        camera = _CAMERA_BY_POSITION["last"]
    else:
        camera = _CAMERA_BY_POSITION["middle"]
    parts.append(camera)

    # 4. 조명
    lighting = _MOOD_LIGHTING.get(bgm_mood or "", "warm natural lighting")
    parts.append(lighting)

    # 5. 아트 스타일 (2D 애니 변형 방지)
    if art_style:
        parts.append(art_style)
    parts.append("consistent character throughout, no morphing, no text, no letters")

    # 조합 (120 단어 이내로 제한)
    prompt = ". ".join(p for p in parts if p)

    # 단어 수 제한 (120단어)
    words = prompt.split()
    if len(words) > 120:
        prompt = " ".join(words[:120])

    logger.info(
        "Pika 프롬프트: scene=%d, type=%s, words=%d",
        scene_order,
        scene_type,
        len(prompt.split()),
    )

    return {
        "prompt": prompt,
        "negative_prompt": preset["negative"],
        "guidance_scale": preset["guidance_scale"],
        "motion": preset["motion"],
        "_scene_type": scene_type,
    }


# ── GPT 시스템 프롬프트 (콘티 생성 시 Pika 최적화 프롬프트도 함께 생성) ──

PIKA_PROMPT_SYSTEM = (
    "You are an expert AI video prompt engineer for Pika v2.2 image-to-video.\n"
    "Generate optimized English video prompts from Korean scene descriptions.\n\n"
    "CRITICAL RULES:\n"
    "1. DO NOT describe the character appearance (reference image handles this)\n"
    "2. ONLY describe: action, background/setting, camera, lighting, mood\n"
    "3. Start with SETTING/BACKGROUND (prevents white background)\n"
    "4. Use specific action verbs (gripping, chopping - not cooking)\n"
    "5. Anchor hands to objects (right hand gripping knife handle)\n"
    "6. ONE action per prompt (never stack multiple actions)\n"
    "7. Keep under 80 words\n"
    "8. Use cinematic language (medium shot, tracking, golden hour)\n"
    "9. NEVER include text/letters/words in the scene\n"
    "10. Maintain 2D anime style - add cel-shaded anime style\n\n"
    "STRUCTURE: [Setting]. [Action with hand positions]. "
    "[Camera]. [Lighting]. [Style], consistent character, no morphing.\n\n"
    "EXAMPLE:\n"
    'Input: "루피가 해적선에서 요리하는 장면"\n'
    'Output: "Inside warm wooden pirate ship galley with copper pots '
    "on walls. Character chops spring greens on cutting board, "
    "right hand gripping knife, left hand pressing vegetables. "
    "Medium shot, gentle drift right. Warm golden light. "
    'Anime cel-shaded, consistent character, no morphing, no text."'
)
