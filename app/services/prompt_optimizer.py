"""프롬프트 최적화 엔진 — Kling AI 가성비 극대화

Kling Elements(5CR)로 최대 품질을 뽑기 위한 프롬프트 전략:
1. 구조화된 프롬프트 (Subject → Action → Style → Camera)
2. 불필요한 토큰 제거 (1000자 제한 내 핵심만)
3. 캐릭터 일관성 유지를 위한 외형 고정 키워드
4. 영상 품질 부스터 키워드 자동 삽입
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# ── 영상 품질 부스터 (Kling Elements 최적화) ──

# 항상 포함되는 품질 키워드
_QUALITY_SUFFIX = (
    "cinematic lighting, smooth camera movement, "
    "high detail, sharp focus, professional quality"
)

# 숏폼 세로 영상에 적합한 카메라 앵글
_CAMERA_ANGLES = {
    "close": "close-up shot",
    "medium": "medium shot",
    "wide": "wide establishing shot",
    "dynamic": "dynamic tracking shot",
    "pov": "first-person POV shot",
}

# 장면 분위기 → 조명 키워드
_MOOD_LIGHTING = {
    "epic": "dramatic golden hour lighting, lens flare",
    "funny": "bright cheerful lighting, vibrant colors",
    "calm": "soft natural lighting, warm tones",
    "tense": "low-key dramatic lighting, deep shadows",
    "sad": "overcast muted lighting, cool blue tones",
    "upbeat": "bright daylight, saturated colors",
    "mysterious": "moody atmospheric lighting, fog",
}


def optimize_scene_prompt(
    *,
    scene_content: str,
    character_desc: str,
    image_prompt: str | None = None,
    has_character: bool = True,
    bgm_mood: str | None = None,
    scene_order: int = 1,
    total_scenes: int = 1,
    duration: int = 5,
) -> str:
    """장면별 최적화된 영상 생성 프롬프트 구성

    Kling Elements 1000자 제한 내에서 최대 효과를 내는 구조:
    [Character] + [Action/Scene] + [Style/Mood] + [Camera] + [Quality]

    Args:
        scene_content: 장면 설명 (한글)
        character_desc: 캐릭터 외형 설명 (영문)
        image_prompt: GPT가 생성한 이미지 프롬프트 (영문, 시작프레임용)
        has_character: 이 장면에 캐릭터가 등장하는지
        bgm_mood: BGM 분위기 (조명 힌트용)
        scene_order: 장면 순서
        total_scenes: 전체 장면 수
        duration: 장면 길이 (초)

    Returns:
        최적화된 영문 프롬프트 (1000자 이내)
    """
    parts: list[str] = []

    # 1. 캐릭터 외형 (등장 시에만, 원본 그대로 고정 — 일관성 최우선)
    #    모든 장면에서 동일한 캐릭터 설명을 사용해야 외형이 유지됨
    if has_character and character_desc:
        parts.append(f"same character throughout: {character_desc}")

    # 2. 장면 동작/내용 (imagePrompt 우선, 없으면 content 변환)
    if image_prompt:
        scene_desc = _clean_prompt(image_prompt)
    else:
        scene_desc = _extract_action(scene_content)
    parts.append(scene_desc)

    # 3. 분위기 조명 (bgm_mood 기반)
    mood_light = _MOOD_LIGHTING.get(bgm_mood or "", "")
    if mood_light:
        parts.append(mood_light)

    # 4. 카메라 앵글 (장면 위치 기반 자동 선택)
    camera = _select_camera(scene_order, total_scenes, duration)
    parts.append(camera)

    # 5. 품질 부스터
    parts.append(_QUALITY_SUFFIX)

    # 조합 + 1000자 제한 (캐릭터 설명은 절대 잘리지 않음)
    prompt = ", ".join(p for p in parts if p)
    if len(prompt) > 950:
        # 캐릭터 설명(첫 파트)은 보호하고 나머지에서 줄임
        char_part = parts[0] if (has_character and character_desc) else ""
        other_parts = parts[1:] if (has_character and character_desc) else parts
        remaining = 950 - len(char_part) - 2  # ", " 연결 고려
        trimmed = _enforce_limit(", ".join(other_parts), max_chars=remaining)
        prompt = f"{char_part}, {trimmed}" if char_part else trimmed

    logger.debug(
        "프롬프트 최적화: scene=%d, len=%d, prompt=%.80s...",
        scene_order, len(prompt), prompt,
    )
    return prompt



def _clean_prompt(prompt: str) -> str:
    """프롬프트에서 불필요한 수식어 제거"""
    # 중복/약한 수식어 제거
    remove_words = [
        "very", "really", "extremely", "absolutely",
        "beautiful", "amazing", "stunning", "gorgeous",
        "ultra realistic", "hyper realistic",
    ]
    cleaned = prompt
    for word in remove_words:
        cleaned = re.sub(
            rf"\b{re.escape(word)}\b,?\s*",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
    return cleaned.strip().rstrip(",").strip()


def _extract_action(content: str) -> str:
    """한글 장면 내용에서 핵심 동작 추출 (영문 변환은 GPT가 이미 함)

    한글이 남아있으면 그대로 전달 (Kling은 영문 권장이지만 한글도 처리 가능)
    """
    # 너무 길면 잘라냄
    return content[:200]


def _select_camera(
    scene_order: int, total_scenes: int, duration: int
) -> str:
    """장면 위치와 길이에 따라 카메라 앵글 자동 선택"""
    if scene_order == 1:
        return _CAMERA_ANGLES["wide"]  # 첫 장면: 전체 분위기 잡기
    if scene_order == total_scenes:
        return _CAMERA_ANGLES["close"]  # 마지막 장면: 클로즈업 임팩트
    if duration >= 8:
        return _CAMERA_ANGLES["dynamic"]  # 긴 장면: 동적 트래킹
    return _CAMERA_ANGLES["medium"]  # 기본: 미디엄 샷


def _enforce_limit(prompt: str, max_chars: int = 950) -> str:
    """프롬프트 길이를 제한 내로 자르기 (문장 단위)"""
    if len(prompt) <= max_chars:
        return prompt

    # 콤마 기준으로 잘라서 마지막 완전한 구간까지
    parts = prompt.split(", ")
    result = []
    current_len = 0
    for part in parts:
        if current_len + len(part) + 2 > max_chars:
            break
        result.append(part)
        current_len += len(part) + 2

    return ", ".join(result)
