"""Hailuo I2V 프롬프트 최적화 엔진 v3

핵심 원칙 (리서치 기반):
1. 이미지에 보이는 것은 반복하지 않음 (동작/변화만 명시)
2. motionPrompt를 우선 사용 (GPT가 생성한 동작 전용 프롬프트)
3. 80-150 단어 이내, 자연스러운 문장 (목록형 금지)
4. 자연스러운 관절/동작 키워드 필수 (로봇 동작 방지)
5. Hailuo [bracket] 카메라 문법 사용
6. 캐릭터 일관성 키워드 필수 삽입
7. artStyle은 영문으로 작성 (Hailuo 모델 호환)
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
        "gentle head nodding, relaxed body posture"
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
        "gentle breathing motion, subtle body sway, natural hand gestures, relaxed organic posture"
    ),
    "talking": (
        "natural lip movement, subtle head tilts, "
        "gentle hand gestures while speaking, "
        "lifelike body language"
    ),
    "default": ("fluid natural motion, smooth weight shift, organic movement, lifelike animation"),
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
    scene_order: int = 1,
    total_scenes: int = 1,
    duration: int = 5,
) -> dict:
    """Hailuo I2V 최적화 프롬프트 v2

    핵심 변경:
    - motionPrompt 우선 사용 (이미지 내용 반복 제거)
    - [bracket] 카메라 문법
    - 자연스러운 문장형 프롬프트 (". " 구분 → ", " 구분)
    - 캐릭터 일관성 강화 키워드
    """
    scene_type = detect_scene_type(scene_content, image_prompt)
    motion_enhancer = MOTION_ENHANCERS.get(scene_type, MOTION_ENHANCERS["default"])

    parts: list[str] = []

    # 1. 배경/세계관 (첫 문장에 — 흰 배경 방지)
    if world_context:
        bg = world_context.strip()
        parts.append(f"In {bg}")

    # 2. 동작 (motionPrompt 우선 — 이미지 내용 반복 금지)
    if motion_prompt:
        # GPT가 생성한 동작 전용 프롬프트 사용
        parts.append(motion_prompt)
    elif scene_content:
        # motionPrompt 없으면 scene_content에서 동작만 추출
        parts.append(scene_content)

    # 3. 보조 캐릭터
    if secondary_character and secondary_character_desc:
        parts.append(f"Together with {secondary_character}: {secondary_character_desc}")

    # 4. 자연스러운 동작 보강 (로봇 동작 방지 핵심)
    parts.append(motion_enhancer)

    # 5. 카메라 (Hailuo [bracket] 문법)
    if scene_order == 1:
        camera = _CAMERA_BY_POSITION["first"]
    elif scene_order == total_scenes:
        camera = _CAMERA_BY_POSITION["last"]
    else:
        camera = _CAMERA_BY_POSITION["middle"]
    parts.append(camera)

    # 6. 조명
    lighting = _MOOD_LIGHTING.get(bgm_mood or "", "natural lighting")
    parts.append(lighting)

    # 7. 아트 스타일 (캐릭터 데이터 기반)
    if art_style:
        parts.append(art_style)

    # 8. 캐릭터 일관성 키워드 (핵심)
    consistency = (
        "consistent character appearance throughout, "
        "same face and proportions, "
        "smooth natural animation, no morphing, no distortion, "
        "no text overlay"
    )
    parts.append(consistency)

    # 자연스러운 문장형 조합 (", " 구분)
    prompt = ", ".join(p for p in parts if p)

    # 150단어 제한 (영문 artStyle 반영으로 확장)
    words = prompt.split()
    if len(words) > 150:
        prompt = " ".join(words[:150])

    logger.info(
        "Hailuo 프롬프트 v2: scene=%d, type=%s, words=%d, has_motion=%s",
        scene_order,
        scene_type,
        len(prompt.split()),
        bool(motion_prompt),
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
        "blurry, low resolution, distorted, extra fingers, "
        "bad anatomy, morphing, shaky camera, text, letters, "
        "words, watermark, signature"
    )
