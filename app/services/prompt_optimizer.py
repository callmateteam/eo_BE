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

    # 1. 카메라 (Hailuo [bracket] 문법 — 반드시 맨 앞)
    if scene_order == 1:
        camera = _CAMERA_BY_POSITION["first"]
    elif scene_order == total_scenes:
        camera = _CAMERA_BY_POSITION["last"]
    else:
        camera = _CAMERA_BY_POSITION["middle"]
    parts.append(camera)

    # 2. 배경/환경 (world_context가 있으면 포함)
    if world_context:
        parts.append(f"Scene set in {world_context}.")

    # 3. 동작 (영어만 — motionPrompt 우선, imagePrompt fallback)
    if motion_prompt:
        parts.append(motion_prompt)
    elif image_prompt:
        parts.append(image_prompt)

    # 4. 동작 보강 (자연스러운 움직임)
    parts.append(motion_enhancer)

    # 5. 캐릭터 보존 + 품질 (반드시 마지막 — 모델이 뒤쪽 지시를 더 잘 따름)
    parts.append(
        "Maintain exact character colors, proportions, and design "
        "from reference image throughout the entire clip. "
        "Smooth fluid animation."
    )

    # 자연스러운 문장형 조합
    prompt = " ".join(p for p in parts if p)

    # 90단어 제한 (짧을수록 캐릭터 보존 우수)
    words = prompt.split()
    if len(words) > 90:
        prompt = " ".join(words[:90])

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
        "blurry, low resolution, distorted, extra fingers, missing fingers, "
        "bad anatomy, morphing, deformation, face change, proportion change, "
        "shaky camera, text, letters, words, watermark, signature, "
        "3d render, realistic, photorealistic"
    )
