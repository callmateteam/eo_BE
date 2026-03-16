"""Hailuo I2V 프롬프트 최적화 엔진

S3 캐릭터 이미지 + 시드 데이터 → Hailuo image-to-video 최적 프롬프트 자동 생성.

핵심 규칙:
1. 이미지에 있는 것은 반복하지 않음 (동작/배경만 명시)
2. 80-120 단어 이내
3. 동작 1-2개만 (한 프롬프트에 너무 많은 행동 금지)
4. 자연스러운 관절/동작 키워드 필수 (로봇 동작 방지)
5. 배경을 첫 문장에 명시
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# ── 장면 유형별 자연스러운 동작 보강 키워드 ──

MOTION_ENHANCERS: dict[str, str] = {
    "cooking": (
        "smooth rhythmic chopping motion, natural arm swing, "
        "elbow bending fluidly, wrist rotating naturally, "
        "body slightly swaying with each chop"
    ),
    "eating": (
        "natural chewing motion, smooth hand-to-mouth movement, "
        "gentle head nodding, relaxed body posture, organic movement"
    ),
    "walking": (
        "natural walking gait with weight shift, "
        "arms swinging naturally, smooth stride, "
        "body momentum flowing forward"
    ),
    "action": (
        "dynamic fluid motion with natural momentum, "
        "smooth weight transfer between poses, "
        "organic follow-through on each movement"
    ),
    "sitting": (
        "gentle breathing motion, subtle body sway, "
        "natural hand gestures, relaxed organic posture"
    ),
    "talking": (
        "natural lip movement, subtle head tilts, "
        "gentle hand gestures while speaking, "
        "lifelike body language"
    ),
    "default": (
        "fluid natural motion, smooth weight shift, "
        "organic movement, lifelike animation"
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

    # 매칭 없으면 첫 번째 추가 이미지 또는 기본 이미지
    if images:
        return f"{base_dir}/{images[0]}"
    return base_image_url


def build_hailuo_prompt(
    *,
    scene_content: str,
    image_prompt: str | None = None,
    character_name: str = "",
    world_context: str = "",
    art_style: str = "",
    series_description: str = "",
    secondary_character: str = "",
    secondary_character_desc: str = "",
    bgm_mood: str | None = None,
    scene_order: int = 1,
    total_scenes: int = 1,
    duration: int = 5,
) -> dict:
    """Hailuo I2V image-to-video 최적화 프롬프트 생성

    로봇 동작 방지를 위해 자연스러운 관절/동작 키워드를 자동 삽입.

    Returns:
        {
            "prompt": str,
            "_scene_type": str,
        }
    """
    scene_type = detect_scene_type(scene_content, image_prompt)
    motion_enhancer = MOTION_ENHANCERS.get(scene_type, MOTION_ENHANCERS["default"])

    parts: list[str] = []

    # 1. 배경/세계관 (첫 문장에 - 흰 배경 방지)
    if world_context:
        parts.append(f"In {world_context.split(',')[0].strip()}")

    # 2. 동작 (이미지에 있는 것은 반복하지 않음 - 동작만)
    if image_prompt:
        parts.append(image_prompt)
    else:
        parts.append(scene_content)

    # 2-1. 보조 캐릭터가 있으면 외형 설명 삽입
    if secondary_character and secondary_character_desc:
        parts.append(
            f"Together with {secondary_character}: {secondary_character_desc}"
        )

    # 3. 자연스러운 동작 보강 (로봇 동작 방지 핵심)
    parts.append(motion_enhancer)

    # 4. 카메라 (Hailuo는 [] 형식 카메라 지원)
    if scene_order == 1:
        camera = _CAMERA_BY_POSITION["first"]
    elif scene_order == total_scenes:
        camera = _CAMERA_BY_POSITION["last"]
    else:
        camera = _CAMERA_BY_POSITION["middle"]
    parts.append(camera)

    # 5. 조명
    lighting = _MOOD_LIGHTING.get(bgm_mood or "", "warm natural lighting")
    parts.append(lighting)

    # 6. 아트 스타일 + 일관성
    if art_style:
        parts.append(art_style)
    parts.append("consistent character throughout, smooth animation, no morphing, no text")

    # 조합 (120 단어 이내로 제한)
    prompt = ". ".join(p for p in parts if p)

    # 단어 수 제한 (120단어)
    words = prompt.split()
    if len(words) > 120:
        prompt = " ".join(words[:120])

    logger.info(
        "Hailuo 프롬프트: scene=%d, type=%s, words=%d",
        scene_order,
        scene_type,
        len(prompt.split()),
    )

    return {
        "prompt": prompt,
        "_scene_type": scene_type,
    }


# 하위 호환: Pika용 함수를 Hailuo용으로 리다이렉트
build_pika_prompt = build_hailuo_prompt
