"""콘티 생성 서비스 - GPT 장면 분할 + GPT 이미지 생성 (Veo 시작 프레임 겸용)"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
from collections.abc import Awaitable, Callable

from app.core.config import settings
from app.core.database import db
from app.core.http_client import get_openai_client
from app.core.s3 import upload_image
from app.services.tts import generate_scene_narrations

logger = logging.getLogger(__name__)

# ── 저작권 캐릭터/시리즈 이름 제거 (OpenAI moderation 우회) ──

_COPYRIGHT_NAMES: list[str] = [
    # 캐릭터 이름 (영문/한글)
    "Monkey D. Luffy", "Monkey D Luffy", "Luffy", "루피",
    "Uzumaki Naruto", "Naruto", "나루토",
    "Anya Forger", "Anya", "아냐",
    "Denji", "덴지",
    "Itadori Yuji", "Yuji", "유지", "이타도리",
    "Gojo Satoru", "Gojo", "고죠",
    "Levi Ackerman", "Levi", "리바이",
    "Eren Yeager", "Eren", "에렌",
    "Kamado Tanjiro", "Tanjiro", "탄지로",
    "Kurosaki Ichigo", "Ichigo", "이치고",
    "Pikachu", "피카츄",
    "Kamado Nezuko", "Nezuko", "네즈코",
    "Totoro", "토토로",
    "Doraemon", "도라에몽",
    "Tony Tony Chopper", "Chopper", "쵸파",
    "Rem", "렘",
    "Asuna Yuuki", "Asuna", "아스나",
    "Mikasa Ackerman", "Mikasa", "미카사",
    "Power", "파워",
    "Killua Zoldyck", "Killua", "키르아",
    # 시리즈 이름
    "One Piece", "원피스", "Naruto Shippuden", "Chainsaw Man", "체인소맨",
    "Jujutsu Kaisen", "주술회전", "Attack on Titan", "진격의 거인",
    "Demon Slayer", "귀멸의 칼날", "Bleach", "블리치",
    "Pokemon", "포켓몬", "My Neighbor Totoro", "이웃집 토토로",
    "Spy x Family", "스파이 패밀리", "Re:Zero", "리제로",
    "Sword Art Online", "소드 아트 온라인", "Hunter x Hunter", "헌터x헌터",
    # 스튜디오 이름 (이미지 프롬프트에서만 제거)
    "Toei Animation", "MAPPA", "ufotable", "WIT Studio", "Studio Pierrot",
    "Madhouse", "CloverWorks", "A-1 Pictures", "Studio Ghibli",
    "White Fox", "Shin-Ei Animation", "OLM",
]

# 길이 내림차순 정렬 (긴 이름 먼저 매칭: "Monkey D. Luffy" > "Luffy")
_COPYRIGHT_NAMES.sort(key=len, reverse=True)
_COPYRIGHT_RE = re.compile(
    "|".join(re.escape(n) for n in _COPYRIGHT_NAMES),
    re.IGNORECASE,
)


def _strip_copyright_names(prompt: str) -> str:
    """이미지 생성 프롬프트에서 저작권 캐릭터/시리즈/스튜디오 이름 제거"""
    cleaned = _COPYRIGHT_RE.sub("", prompt)
    # 연속 공백/쉼표 정리
    cleaned = re.sub(r",\s*,", ",", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned.strip()


# ── GPT 콘티 생성 프롬프트 (토큰 최적화) ──

STORYBOARD_SYSTEM = """\
Short-form video storyboard creator for image-to-video pipeline.
Create scene cuts from character + idea.

Rules:
- Total ≤ 60s, each scene 3-10s
- Output ONLY valid JSON array
- 3-5 scenes (strictly, never more than 5)
- imagePrompt: English, max 30 words. Describe ONLY the SCENE, \
NOT the character's appearance. The character description will be \
added automatically by the system. Focus on: \
(1) character POSE/POSITION (e.g. sitting, running, holding something), \
(2) background/location matching world context, (3) key props. \
Static opening freeze-frame, NOT mid-action. \
NO text/letters/words in the image. \
NEVER include character appearance details (hair, eyes, outfit) — \
those are handled separately. \
NEVER use character names, series names, or franchise names. \
IMPORTANT: Always describe clear, simple poses where hands and limbs \
are fully visible and not overlapping. Avoid complex hand gestures. \
Prefer poses like: arms at sides, hands on table, hands behind back, \
arms crossed. Keep hands away from face. \
IMPORTANT: Be precise about spatial relationships. \
Use "seated in a chair at a desk" NOT "sitting at a table". \
Use "standing next to" NOT "on". \
Always clarify whether the character is ON or NEXT TO furniture.
- motionPrompt: English, max 30 words. Describe ONLY the motion/action \
that should happen in this scene. Do NOT repeat what's visible in \
the image. Be SPECIFIC and PHYSICAL: describe exact body part movements, \
direction, speed. Example: "Character swings right arm forward in a punch, \
body rotating left, legs planted wide" NOT "Character attacks".
- title: Korean, short (2-5 words)
- content: Korean, 2-3 sentences describing the scene in detail. \
Include: what the character is doing, their expression/emotion, \
the environment/atmosphere, and any important objects or interactions. \
Write as if explaining the scene to a viewer.
- duration: action=short, dialogue=longer
- hasCharacter: true if the character appears in this scene
- secondaryCharacter: Korean name of another character mentioned in \
the idea (null if none). If the idea mentions ANY other character \
besides the main one, you MUST fill this field. \
Example: if idea says "피카츄와 파이리가 싸운다", secondaryCharacter="파이리".
- secondaryCharacterDesc: English visual description of the secondary \
character. REQUIRED if secondaryCharacter is not null. \
Describe their APPEARANCE in detail based on your knowledge: \
body shape, color, size, distinctive features. \
NEVER use the character's name — describe ONLY how they look. \
Example: for 파이리 → "small orange bipedal lizard with a flame \
burning at the tip of its tail, blue eyes, cream-colored belly". \
For 리자몽 → "large orange dragon with wings, flame on tail tip". \
Also include this secondary character in imagePrompt scenes \
where they appear. Keep secondary character poses simple: \
arms at sides, arms crossed, hands in pockets, or hands behind back. \
Avoid complex hand gestures for ALL characters.
- narration: Korean subtitle for 2025-2026 short-form video. REQUIRED, never null. \
MAX 15 characters. Use trendy Gen-Z Korean internet slang. \
MUST reflect what's actually happening in THIS specific scene. \
Style rules: \
  - NEVER use "~합니다/~입니다". Use "~임", "~하는 중", "~각" instead. \
  - Reactions: "실화냐", "킹받음", "미쳤다", "오열각", "개웃김" \
  - Situation: "[상황]+각" (망각, 사랑각, 현피각), "[동사]+하는 중" \
  - Editor voice: "(사실 좋아하는 중)", "결국 이렇게 됨" \
  - Emphasis: "개~" prefix, "찐", "걍", "어케" \
Good: "킹받는 중..", "이게 내 잘못임?", "망각 시작ㅋㅋ", "걍 도망치고 싶음" \
Bad: "헐 대박" (too generic), "피카츄는 놀고 있습니다" (formal narrator) \
NEVER copy the examples — write unique text matching the scene context. \
If narrationStyle is "character", write as the character's inner voice.
- narrationStyle: "character"|"narrator" (always pick one, never "none")
- bgmMood: overall BGM mood (first scene only): \
epic/funny/calm/tense/sad/upbeat/mysterious
- Vary visual composition: mix close-ups, medium, wide shots across scenes.

[{"title":"","content":"","imagePrompt":"","motionPrompt":"",\
"duration":5.0,"hasCharacter":true,"secondaryCharacter":null,\
"secondaryCharacterDesc":null,\
"narration":"","narrationStyle":"character","bgmMood":"funny"}]"""

STORYBOARD_USER = """\
캐릭터: {character_desc}
세계관/배경: {world_context}
아트 스타일: {art_style}
아이디어: {idea}
{enriched_section}\
60초 이내 숏폼 콘티 생성. 배경은 세계관에 맞게 구성.
NOTE: imagePrompt에 캐릭터 외형을 쓰지 마세요. 장면/포즈/배경만 작성."""

# 이미지 동시 요청 제한 (rate limit 방지) - 지연 초기화
_IMAGE_SEMAPHORE: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
    """이벤트 루프 시작 후 세마포어 지연 생성"""
    global _IMAGE_SEMAPHORE  # noqa: PLW0603
    if _IMAGE_SEMAPHORE is None:
        _IMAGE_SEMAPHORE = asyncio.Semaphore(1)
    return _IMAGE_SEMAPHORE


def _build_enriched_section(enriched_idea: dict | None) -> str:
    """enrichedIdea JSON을 프롬프트 텍스트로 변환한다."""
    if not enriched_idea:
        return ""
    parts = []
    if enriched_idea.get("background"):
        parts.append(f"배경 설정: {enriched_idea['background']}")
    if enriched_idea.get("mood"):
        parts.append(f"분위기/톤: {enriched_idea['mood']}")
    if enriched_idea.get("main_character"):
        parts.append(f"메인 캐릭터 상세: {enriched_idea['main_character']}")
    if enriched_idea.get("supporting_characters"):
        chars = ", ".join(enriched_idea["supporting_characters"])
        parts.append(f"보조 캐릭터: {chars}")
    if enriched_idea.get("story"):
        parts.append(f"스토리 구조: {enriched_idea['story']}")
    if parts:
        return "\n".join(parts) + "\n"
    return ""


async def generate_scenes_with_gpt(
    character_desc: str,
    idea: str,
    *,
    world_context: str = "",
    art_style: str = "",
    enriched_idea: dict | None = None,
) -> tuple[list[dict], str | None]:
    """GPT-4o-mini로 콘티 장면 분할 생성 (최대 3회 재시도)"""
    client = get_openai_client()
    max_retries = 3
    last_error: Exception | None = None
    enriched_section = _build_enriched_section(enriched_idea)

    for attempt in range(1, max_retries + 1):
        try:
            async with asyncio.timeout(60):
                resp = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "gpt-4o-mini",
                        "max_tokens": 2000,
                        "temperature": 0.7 + (attempt - 1) * 0.1,
                        "response_format": {"type": "json_object"},
                        "messages": [
                            {"role": "system", "content": STORYBOARD_SYSTEM},
                            {
                                "role": "user",
                                "content": STORYBOARD_USER.format(
                                    character_desc=character_desc,
                                    idea=idea,
                                    world_context=world_context or "일반적인 배경",
                                    art_style=art_style or "anime style",
                                    enriched_section=enriched_section,
                                ),
                            },
                        ],
                    },
                )
                resp.raise_for_status()
                raw = resp.json()["choices"][0]["message"]["content"].strip()
                logger.debug("GPT 콘티 응답 (시도 %d): %s", attempt, raw[:300])
                parsed = json.loads(raw)

                # response_format=json_object는 객체를 반환하므로 배열 추출
                if isinstance(parsed, list):
                    scenes = parsed
                else:
                    for key in ("scenes", "data", "storyboard", "cuts"):
                        if key in parsed and isinstance(parsed[key], list):
                            scenes = parsed[key]
                            break
                    else:
                        scenes = []

                if not scenes:
                    logger.warning(
                        "GPT 콘티 파싱 실패 (시도 %d/%d): keys=%s",
                        attempt, max_retries, list(parsed.keys()) if isinstance(parsed, dict) else type(parsed),
                    )
                    last_error = ValueError("GPT가 유효한 장면을 생성하지 못했습니다")
                    continue

                # 성공
                break

        except Exception as exc:
            logger.warning("GPT 콘티 생성 에러 (시도 %d/%d): %s", attempt, max_retries, exc)
            last_error = exc
            if attempt < max_retries:
                await asyncio.sleep(2)
            continue
    else:
        raise last_error or ValueError("GPT 콘티 생성 실패 (재시도 소진)")

    # bgmMood 추출 (첫 장면에서)
    bgm_mood = None
    for s in scenes:
        if s.get("bgmMood"):
            bgm_mood = str(s["bgmMood"])[:50]
            break

    # 필드 검증 및 정규화
    validated: list[dict] = []
    for s in scenes:
        narration_raw = s.get("narration")
        narration = str(narration_raw)[:1000] if narration_raw else None
        narration_style = str(s.get("narrationStyle", "narrator"))
        if narration_style not in ("character", "narrator"):
            narration_style = "narrator"
        # narration이 없으면 content 첫 문장을 나레이션으로 사용
        if not narration:
            content_text = str(s.get("content", ""))
            narration = content_text.split(".")[0].strip()[:200] or None
        if not narration:
            narration_style = "none"

        # 보조 캐릭터 외형 묘사 추출
        sec_desc = str(s.get("secondaryCharacterDesc") or "")[:300]
        # imagePrompt는 씬 설명만 저장 (character_desc는 이미지 생성 시점에 합성)
        scene_prompt = str(s.get("imagePrompt", ""))
        if sec_desc:
            img_prompt = (
                f"{scene_prompt}. "
                f"Also in the scene: {sec_desc}. "
                "Every character has exactly two arms, two hands with five fingers each. "
                "No extra or missing limbs for any character."
            )
        else:
            img_prompt = scene_prompt

        validated.append(
            {
                "title": str(s.get("title", "장면"))[:100],
                "content": str(s.get("content", ""))[:2000],
                "imagePrompt": img_prompt[:500],
                "motionPrompt": str(s.get("motionPrompt", ""))[:200],
                "duration": min(max(float(s.get("duration", 5.0)), 2.0), 10.0),
                "hasCharacter": bool(s.get("hasCharacter", True)),
                "secondaryCharacter": str(s.get("secondaryCharacter") or "")[:100] or None,
                "narration": narration,
                "narrationStyle": narration_style,
            }
        )

    # 총 duration 60초 초과 시 비례 조정
    total = sum(s["duration"] for s in validated)
    if total > 60:
        ratio = 60.0 / total
        for s in validated:
            s["duration"] = round(s["duration"] * ratio, 1)

    return validated, bgm_mood


async def generate_scene_image(
    image_prompt: str,
    character_desc: str,
    user_id: str,
    *,
    reference_image_url: str | None = None,
    art_style: str = "",
    world_context: str = "",
    bgm_mood: str | None = None,
    character_name: str = "",
    enriched_background: str = "",
) -> tuple[str, bytes]:
    """FLUX로 장면 시작 프레임 생성 → S3 업로드

    - 첫 장면 (reference 없음): FLUX dev (text-to-image)
    - 나머지 장면 (reference 있음): FLUX Kontext (image-to-image)
    - 저작권 필터 없음 → 캐릭터 이름 그대로 사용 가능
    """
    from app.services.prompt_optimizer import translate_context_to_english_async

    # 스타일
    style_text = art_style or "2D anime cel-shaded style, flat colors, bold outlines, vibrant palette"

    # 조명
    mood_lighting = {
        "epic": "dramatic golden hour lighting with lens flare",
        "funny": "bright cheerful lighting with vibrant colors",
        "calm": "soft natural lighting with warm tones",
        "tense": "low-key dramatic lighting with deep shadows",
        "sad": "overcast muted lighting with cool blue tones",
        "mysterious": "moody atmospheric lighting with fog",
    }
    lighting = mood_lighting.get(bgm_mood or "", "natural lighting")

    # 배경 컨텍스트 (enriched_background 우선 → world_context 폴백)
    bg_text = ""
    if enriched_background:
        bg_en = await translate_context_to_english_async(enriched_background)
        bg_text = f"Background setting: {bg_en}. "
    elif world_context:
        wc_en = await translate_context_to_english_async(world_context)
        bg_text = f"Background setting: {wc_en}. "

    # 캐릭터 이름을 프롬프트에 포함 (FLUX는 저작권 필터 없음)
    name_text = f"{character_name}. " if character_name else ""

    # 해부학 방어 (손가락/팔 개수 오류 방지)
    anatomy_guard = (
        "Anatomically correct: exactly two arms, two hands with five fingers each, "
        "two legs. No extra or missing limbs. No deformed hands or fingers."
    )

    if reference_image_url:
        # Kontext: 레퍼런스 이미지가 캐릭터를 정의하므로 캐릭터 외형 묘사 제거
        # character_desc가 image_prompt 앞에 붙어있으면 제거 (씬 묘사만 남김)
        scene_only_prompt = image_prompt
        if character_desc and scene_only_prompt.startswith(character_desc):
            scene_only_prompt = scene_only_prompt[len(character_desc):].lstrip(". ")

        full_prompt = (
            f"{scene_only_prompt}. "
            f"{bg_text}"
            f"Same character identity, body shape, and color palette as reference image. "
            f"Match the character's pose and expression from the reference image. "
            f"New camera angle for variety. "
            f"{style_text}. {lighting}. "
            f"{anatomy_guard}. "
            "No lightning effects, no weather effects inside the room. "
            "No text or letters in the image."
        )[:2000]
    else:
        # FLUX dev: 텍스트만으로 캐릭터 생성 → 상세 묘사 필요
        full_prompt = (
            f"{name_text}{character_desc}. "
            f"{image_prompt}. "
            f"{bg_text}"
            f"{style_text}. {lighting}. "
            f"{anatomy_guard}. "
            "No text or letters in the image."
        )[:4000]

    async with _get_semaphore():
        if reference_image_url:
            img_data = await _generate_with_flux_kontext(full_prompt, reference_image_url)
        else:
            img_data = await _generate_with_flux_dev(full_prompt)

    s3_url = await asyncio.to_thread(
        upload_image,
        img_data,
        user_id,
        content_type="image/jpeg",
        folder="storyboard-scenes",
    )
    return s3_url, img_data


async def _generate_with_flux_dev(prompt: str) -> bytes:
    """FLUX dev text-to-image (첫 장면용, 레퍼런스 없음)"""
    client = get_openai_client()
    max_retries = 3
    for attempt in range(max_retries):
        async with asyncio.timeout(120):
            resp = await client.post(
                "https://fal.run/fal-ai/flux/dev",
                headers={
                    "Authorization": f"Key {settings.FAL_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "prompt": prompt,
                    "image_size": {"width": 1024, "height": 1024},
                    "num_images": 1,
                    "num_inference_steps": 28,
                    "guidance_scale": 7.0,
                },
            )
            if resp.status_code == 429:
                wait = 10 * (attempt + 1)
                logger.warning("FLUX dev 429 rate limit, %d초 후 재시도 (%d/%d)", wait, attempt + 1, max_retries)
                await asyncio.sleep(wait)
                continue
            if resp.status_code != 200:
                logger.error(
                    "FLUX dev 이미지 생성 실패 (%s): %s", resp.status_code, resp.text[:500]
                )
                resp.raise_for_status()
            result = resp.json()
            break
    else:
        raise RuntimeError("FLUX dev 이미지 생성 실패: 최대 재시도 초과 (429)")

    image_url = result["images"][0]["url"]
    logger.info("FLUX dev 이미지 생성 완료: %s", image_url)

    # 이미지 다운로드
    dl = get_openai_client()
    img_resp = await dl.get(image_url)
    img_resp.raise_for_status()
    return img_resp.content


async def _generate_with_flux_kontext(prompt: str, reference_image_url: str) -> bytes:
    """FLUX Kontext image-to-image (나머지 장면용, 히어로 프레임 참조)"""
    client = get_openai_client()
    max_retries = 3
    for attempt in range(max_retries):
        try:
            async with asyncio.timeout(180):  # 120→180초 (fal.ai 큐 지연 대응)
                resp = await client.post(
                    "https://fal.run/fal-ai/flux-pro/kontext",
                    headers={
                        "Authorization": f"Key {settings.FAL_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "prompt": prompt,
                        "image_url": reference_image_url,
                        "aspect_ratio": "1:1",
                        "num_inference_steps": 28,
                        "guidance_scale": 4.0,
                        "num_images": 1,
                        "output_format": "png",
                        "safety_tolerance": "6",
                    },
                )
                if resp.status_code == 429:
                    wait = 10 * (attempt + 1)
                    logger.warning("FLUX Kontext 429 rate limit, %d초 후 재시도 (%d/%d)", wait, attempt + 1, max_retries)
                    await asyncio.sleep(wait)
                    continue
                if resp.status_code != 200:
                    logger.error(
                        "FLUX Kontext 이미지 생성 실패 (%s): %s", resp.status_code, resp.text[:500]
                    )
                    resp.raise_for_status()
                result = resp.json()
                break
        except TimeoutError:
            logger.warning(
                "FLUX Kontext 타임아웃 (%d/%d), %s",
                attempt + 1, max_retries,
                "재시도..." if attempt < max_retries - 1 else "최종 실패",
            )
            if attempt < max_retries - 1:
                await asyncio.sleep(5)
                continue
            raise
    else:
        raise RuntimeError("FLUX Kontext 이미지 생성 실패: 최대 재시도 초과 (429)")

    image_url = result["images"][0]["url"]
    logger.info("FLUX Kontext 이미지 생성 완료: %s", image_url)

    # 이미지 다운로드
    dl = get_openai_client()
    img_resp = await dl.get(image_url)
    img_resp.raise_for_status()
    return img_resp.content


class CharacterInfo:
    """캐릭터 설명 + 음성 설정 + 원본 이미지 + 세계관/스타일 + 이름 + 에셋"""

    def __init__(
        self,
        description: str,
        voice_id: str,
        voice_style: str,
        image_url: str | None = None,
        world_context: str = "",
        art_style: str = "",
        name: str = "",
        extra_images: str = "",
    ) -> None:
        self.description = description
        self.voice_id = voice_id
        self.voice_style = voice_style
        self.image_url = image_url
        self.world_context = world_context
        self.art_style = art_style
        self.name = name
        self.extra_images = extra_images


async def get_character_description(
    character_id: str | None,
    custom_character_id: str | None,
) -> str:
    """캐릭터 ID로 설명 텍스트 조회"""
    info = await get_character_info(character_id, custom_character_id)
    return info.description


async def get_character_info(
    character_id: str | None,
    custom_character_id: str | None,
) -> CharacterInfo:
    """캐릭터 ID로 설명 + 음성 설정 조회 (디테일 포함)"""
    if character_id:
        char = await db.character.find_unique(where={"id": character_id})
        if not char:
            raise ValueError("캐릭터를 찾을 수 없습니다")
        desc = char.promptFeatures or char.veoPrompt or ""
        return CharacterInfo(
            description=desc,
            voice_id=char.voiceId,
            voice_style=char.voiceStyle,
            image_url=char.imageUrl,
            world_context=getattr(char, "worldContext", "") or "",
            art_style=getattr(char, "artStyle", "") or "",
            name=char.nameEn or char.name or "",
            extra_images=getattr(char, "extraImages", "") or "",
        )
    if custom_character_id:
        cc = await db.customcharacter.find_unique(where={"id": custom_character_id})
        if not cc:
            raise ValueError("커스텀 캐릭터를 찾을 수 없습니다")
        if cc.status != "COMPLETED" or not cc.veoPrompt:
            raise ValueError("아직 생성 중이거나 실패한 캐릭터입니다")
        from app.schemas.custom_character import STYLE_PROMPT, CharacterStyle

        style_prompt = ""
        try:
            style_prompt = STYLE_PROMPT.get(CharacterStyle(cc.style), "")
        except ValueError:
            pass
        return CharacterInfo(
            description=cc.veoPrompt,
            voice_id=cc.voiceId,
            voice_style=cc.voiceStyle,
            image_url=cc.imageUrl1 or cc.imageUrl2 or None,
            world_context="",
            art_style=style_prompt,
            name=cc.name or "",
        )
    raise ValueError("캐릭터를 선택해주세요")


async def get_secondary_character_description(name: str) -> str:
    """보조 캐릭터 외형 설명 조회. DB에 있으면 promptFeatures 사용, 없으면 GPT 생성."""
    if not name:
        return ""

    # 1. DB에서 이름으로 검색 (한글/영문 모두)
    char = await db.character.find_first(
        where={"OR": [{"name": {"contains": name}}, {"nameEn": {"contains": name}}]}
    )
    if char:
        logger.info("보조 캐릭터 DB 매칭: %s → %s", name, char.name)
        return char.promptFeatures or char.veoPrompt or ""

    # 2. DB에 없으면 GPT로 외형 설명 생성
    logger.info("보조 캐릭터 DB에 없음, GPT 생성: %s", name)
    try:
        client = get_openai_client()
        async with asyncio.timeout(15):
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "gpt-4o-mini",
                    "temperature": 0,
                    "max_tokens": 200,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "Describe the anime/cartoon character's "
                                "physical appearance in English for video "
                                "generation. Include: height, build, hair "
                                "color/style, eye color, clothing, "
                                "distinctive features. Max 50 words. "
                                "No personality or story, only visual."
                            ),
                        },
                        {
                            "role": "user",
                            "content": f"Describe: {name}",
                        },
                    ],
                },
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        logger.exception("보조 캐릭터 GPT 설명 생성 실패: %s", name)
        return ""


async def process_storyboard(
    storyboard_id: str,
    user_id: str,
    character_desc: str,
    idea: str,
    progress_callback: Callable[[int, str], Awaitable[None]] | None = None,
    *,
    voice_id: str = "alloy",
    voice_style: str = "",
    character_image_url: str | None = None,
    project_id: str | None = None,
    world_context: str = "",
    art_style: str = "",
    character_name: str = "",
    enriched_idea: dict | None = None,
    extra_images: str = "",
) -> None:
    """콘티 생성 전체 파이프라인 (백그라운드)"""

    async def notify(pct: int, step: str) -> None:
        if progress_callback:
            await progress_callback(pct, step)

    try:
        # Step 1: GPT 장면 분할 (0-30%)
        await notify(10, "AI가 장면을 구성하고 있습니다...")
        scenes, bgm_mood = await generate_scenes_with_gpt(
            character_desc,
            idea,
            world_context=world_context,
            art_style=art_style,
            enriched_idea=enriched_idea,
        )
        await notify(30, f"{len(scenes)}개 장면 생성 완료")

        # bgmMood 저장
        if bgm_mood:
            await db.storyboard.update(
                where={"id": storyboard_id},
                data={"bgmMood": bgm_mood},
            )

        # Step 2: DB에 장면 저장 (30-40%)
        await notify(35, "장면 저장 중...")

        # 보조 캐릭터 외형 설명 일괄 조회 (중복 제거)
        secondary_names = {s["secondaryCharacter"] for s in scenes if s.get("secondaryCharacter")}
        secondary_descs: dict[str, str] = {}
        for sec_name in secondary_names:
            desc = await get_secondary_character_description(sec_name)
            secondary_descs[sec_name] = desc
            logger.info("보조 캐릭터 설명: %s → %d자", sec_name, len(desc))

        for i, scene in enumerate(scenes):
            sec_name = scene.get("secondaryCharacter")
            await db.storyboardscene.create(
                data={
                    "storyboardId": storyboard_id,
                    "sceneOrder": i + 1,
                    "title": scene["title"],
                    "content": scene["content"],
                    "imagePrompt": scene["imagePrompt"],
                    "motionPrompt": scene.get("motionPrompt", ""),
                    "duration": scene["duration"],
                    "hasCharacter": scene["hasCharacter"],
                    "secondaryCharacter": sec_name,
                    "secondaryCharacterDesc": secondary_descs.get(sec_name or "", "") or None,
                    "narration": scene["narration"],
                    "narrationStyle": scene["narrationStyle"],
                    "imageStatus": "GENERATING",
                }
            )
        await notify(40, "장면 저장 완료")

        # Step 3+4: 이미지 생성 + TTS 병렬 실행 (40-90%)
        db_scenes = await db.storyboardscene.find_many(
            where={"storyboardId": storyboard_id},
            order={"sceneOrder": "asc"},
        )

        await notify(45, "장면 이미지 생성 + 나레이션 동시 시작...")

        # 첫 장면 이미지를 먼저 생성 (히어로 프레임 + 참조용)
        # 항상 캐릭터 원본 image.png를 레퍼런스로 고정 → 캐릭터 일관성 보장
        enriched_bg = enriched_idea.get("background", "") if enriched_idea else ""

        hero_url: str | None = None
        if db_scenes:
            first = db_scenes[0]
            try:
                url, _ = await generate_scene_image(
                    image_prompt=first.imagePrompt,
                    character_desc=character_desc,
                    user_id=user_id,
                    reference_image_url=character_image_url,
                    art_style=art_style,
                    world_context=world_context,
                    bgm_mood=bgm_mood,
                    character_name=character_name,
                    enriched_background=enriched_bg,
                )
                hero_url = url
                await db.storyboardscene.update(
                    where={"id": first.id},
                    data={"imageUrl": url, "imageStatus": "COMPLETED"},
                )
                await db.storyboard.update(
                    where={"id": storyboard_id},
                    data={"heroFrameUrl": url},
                )
            except Exception:
                logger.exception("첫 장면 이미지 생성 실패")
                # fallback: 캐릭터 기존 이미지를 썸네일로 사용
                if character_image_url:
                    logger.info("fallback: 캐릭터 이미지를 썸네일로 사용 (%s)", first.id)
                    await db.storyboardscene.update(
                        where={"id": first.id},
                        data={"imageUrl": character_image_url, "imageStatus": "COMPLETED"},
                    )
                    await db.storyboard.update(
                        where={"id": storyboard_id},
                        data={"heroFrameUrl": character_image_url},
                    )
                else:
                    await db.storyboardscene.update(
                        where={"id": first.id},
                        data={"imageStatus": "FAILED"},
                    )

        await notify(55, "첫 장면 완료, 나머지 병렬 생성 중...")

        # 나머지 장면 이미지 생성 (병렬, 세마포어 제한)
        # 항상 캐릭터 원본 image.png 고정 레퍼런스 (hero_url 체이닝 제거)
        async def _gen_scene_image(sc: object) -> None:
            try:
                url, _ = await generate_scene_image(
                    image_prompt=sc.imagePrompt,
                    character_desc=character_desc,
                    user_id=user_id,
                    reference_image_url=character_image_url or hero_url,
                    art_style=art_style,
                    world_context=world_context,
                    bgm_mood=bgm_mood,
                    character_name=character_name,
                    enriched_background=enriched_bg,
                )
                await db.storyboardscene.update(
                    where={"id": sc.id},
                    data={"imageUrl": url, "imageStatus": "COMPLETED"},
                )
            except Exception:
                logger.exception("장면 이미지 생성 실패: %s", sc.id)
                # fallback: 캐릭터 기존 이미지를 썸네일로 사용
                if character_image_url:
                    logger.info("fallback: 캐릭터 이미지를 썸네일로 사용 (%s)", sc.id)
                    await db.storyboardscene.update(
                        where={"id": sc.id},
                        data={"imageUrl": character_image_url, "imageStatus": "COMPLETED"},
                    )
                else:
                    await db.storyboardscene.update(
                        where={"id": sc.id},
                        data={"imageStatus": "FAILED"},
                    )

        # TTS 나레이션 생성 (병렬)
        async def _gen_tts() -> None:
            tts_scenes = await db.storyboardscene.find_many(
                where={"storyboardId": storyboard_id},
                order={"sceneOrder": "asc"},
            )
            await generate_scene_narrations(
                scenes=tts_scenes,
                voice_id=voice_id,
                voice_style=voice_style,
                user_id=user_id,
            )

        # 이미지(2~N번 장면) + TTS 동시 실행
        image_tasks = [_gen_scene_image(sc) for sc in db_scenes[1:]]
        await asyncio.gather(
            asyncio.gather(*image_tasks),
            _gen_tts(),
            return_exceptions=True,
        )

        await notify(90, "이미지 + 나레이션 생성 완료")

        # Step 5: 완료 여부 확인 (90-100%)
        failed_count = await db.storyboardscene.count(
            where={
                "storyboardId": storyboard_id,
                "imageStatus": "FAILED",
            },
        )
        if failed_count == len(db_scenes):
            raise ValueError("모든 장면 이미지 생성에 실패했습니다")

        await db.storyboard.update(
            where={"id": storyboard_id},
            data={"status": "READY"},
        )

        # 프로젝트에 스토리보드 연결 + stage 3 자동 진행
        if project_id:
            from app.services.project import link_storyboard

            await link_storyboard(project_id, storyboard_id)

        msg = "콘티 생성 완료!"
        if failed_count > 0:
            msg = f"콘티 생성 완료 ({failed_count}개 이미지 재생성 필요)"
        await notify(100, msg)

    except Exception as e:
        logger.exception("콘티 생성 실패: %s", storyboard_id)
        try:
            await db.storyboard.update(
                where={"id": storyboard_id},
                data={"status": "FAILED", "errorMsg": str(e)[:500]},
            )
        except Exception:
            logger.exception("FAILED 상태 업데이트 실패: %s", storyboard_id)
        if progress_callback:
            await progress_callback(-1, "콘티 생성에 실패했습니다")


async def content_to_image_prompt(
    content: str,
    character_desc: str,
    *,
    background_context: str = "",
) -> str:
    """콘티 설명(한글)을 이미지 생성용 영문 프롬프트로 변환

    캐릭터 묘사는 GPT에게 맡기지 않고, 장면 묘사만 영문 변환 후
    코드에서 캐릭터 묘사를 앞에 직접 붙인다 (일관성 보장).

    background_context가 주어지면 기존 씬의 배경/장소를 유지하도록 강제한다.
    """
    bg_instruction = ""
    if background_context:
        bg_instruction = (
            f" IMPORTANT: This scene takes place in the SAME location as "
            f"the other scenes: {background_context}. Keep the background "
            f"setting consistent. Do NOT change the location."
        )

    client = get_openai_client()
    async with asyncio.timeout(30):
        resp = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "gpt-4o-mini",
                "max_tokens": 100,
                "temperature": 0.3,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Convert Korean scene description to English "
                            "image prompt. Max 30 words. Describe ONLY the "
                            "scene action, pose, background, and props. "
                            "Do NOT describe the character's appearance "
                            "(hair, eyes, outfit) — that will be added "
                            "separately. NEVER include text/letters/words."
                            f"{bg_instruction}"
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"장면 설명: {content}",
                    },
                ],
            },
        )
        resp.raise_for_status()
        scene_prompt = resp.json()["choices"][0]["message"]["content"].strip()
        words = scene_prompt.split()
        if len(words) > 30:
            scene_prompt = " ".join(words[:30]).rstrip(",")
        # 캐릭터 묘사를 앞에 고정 (GPT가 변형 불가)
        return f"{character_desc}. {scene_prompt}"


async def regenerate_scene_image_task(
    scene_id: str,
    character_desc: str,
    user_id: str,
    progress_callback: Callable[[int, str], Awaitable[None]] | None = None,
) -> None:
    """장면 시작 프레임 재생성 (콘티 설명 기반으로 프롬프트 재생성)"""

    async def notify(pct: int, step: str) -> None:
        if progress_callback:
            await progress_callback(pct, step)

    try:
        scene = await db.storyboardscene.find_unique(where={"id": scene_id})
        if not scene:
            raise ValueError("장면을 찾을 수 없습니다")

        await db.storyboardscene.update(
            where={"id": scene_id},
            data={"imageStatus": "GENERATING"},
        )
        await notify(15, "콘티 설명을 분석하고 있습니다...")

        # 기존 씬들의 배경 컨텍스트 추출 (첫 번째 씬의 content에서)
        first_scene = await db.storyboardscene.find_first(
            where={"storyboardId": scene.storyboardId, "sceneOrder": 1},
        )
        background_context = ""
        if first_scene and first_scene.id != scene.id:
            # 첫 씬의 content에서 배경 힌트 추출
            background_context = first_scene.content[:200]

        # 프로젝트의 enrichedIdea에서 배경 정보도 확인
        linked_project = await db.project.find_first(
            where={"storyboardId": scene.storyboardId},
        )
        if linked_project and getattr(linked_project, "enrichedIdea", None):
            enriched = linked_project.enrichedIdea
            if isinstance(enriched, dict) and enriched.get("background"):
                background_context = enriched["background"]

        # 현재 content 기반으로 새 imagePrompt 생성 (배경 컨텍스트 포함)
        new_prompt = await content_to_image_prompt(
            scene.content, character_desc,
            background_context=background_context,
        )
        await notify(35, "이미지 프롬프트 생성 완료")

        # 레퍼런스 이미지 조회 (캐릭터 + 배경 일관성 유지)
        # 우선순위: hero frame > 캐릭터 프리셋 이미지
        # hero frame은 캐릭터 + 아트 스타일 + 배경이 모두 녹아있어
        # 재생성 시에도 기존 씬들과 동일한 분위기를 유지한다.
        storyboard = await db.storyboard.find_unique(
            where={"id": scene.storyboardId},
        )
        ref_url = None
        art_style = ""
        world_context = ""
        bgm_mood = None
        char_name = ""

        # 1순위: hero frame (기존 씬과 배경/스타일 일관성)
        if storyboard and storyboard.heroFrameUrl:
            ref_url = storyboard.heroFrameUrl
        # 2순위: 캐릭터 프리셋 이미지 (hero frame 없을 때)
        if not ref_url:
            if storyboard and storyboard.characterId:
                char = await db.character.find_unique(where={"id": storyboard.characterId})
                if char:
                    ref_url = char.imageUrl
            elif storyboard and storyboard.customCharacterId:
                cc = await db.customcharacter.find_unique(where={"id": storyboard.customCharacterId})
                if cc:
                    ref_url = cc.imageUrl1

        # 캐릭터 메타 정보 (아트 스타일, 세계관, BGM)
        if storyboard and storyboard.characterId:
            char = await db.character.find_unique(where={"id": storyboard.characterId})
            if char:
                art_style = char.artStyle or ""
                world_context = char.worldContext or ""
                char_name = char.name or ""
        elif storyboard and storyboard.customCharacterId:
            cc = await db.customcharacter.find_unique(where={"id": storyboard.customCharacterId})
            if cc:
                char_name = cc.name or ""
        if storyboard:
            bgm_mood = storyboard.bgmMood

        await notify(45, "AI가 시작 프레임을 생성하고 있습니다...")
        s3_url, _ = await generate_scene_image(
            new_prompt, character_desc, user_id,
            reference_image_url=ref_url,
            art_style=art_style,
            world_context=world_context,
            bgm_mood=bgm_mood,
            character_name=char_name,
        )

        # 이미지 + 새 프롬프트 모두 DB에 저장
        await db.storyboardscene.update(
            where={"id": scene_id},
            data={
                "imageUrl": s3_url,
                "imagePrompt": new_prompt,
                "imageStatus": "COMPLETED",
            },
        )
        await notify(100, "이미지 재생성 완료!")

    except Exception:
        logger.exception("이미지 재생성 실패: %s", scene_id)
        try:
            await db.storyboardscene.update(
                where={"id": scene_id},
                data={"imageStatus": "FAILED"},
            )
        except Exception:
            logger.exception("FAILED 상태 업데이트 실패: %s", scene_id)
        if progress_callback:
            await progress_callback(-1, "이미지 생성에 실패했습니다")


# ── API 레이어에서 호출하는 DB 조회/수정 함수 ──


async def count_generating_storyboards(user_id: str) -> int:
    """유저의 GENERATING 상태 콘티 개수를 반환한다."""
    return await db.storyboard.count(
        where={"userId": user_id, "status": "GENERATING"},
    )


async def create_storyboard_record(
    idea: str,
    character_id: str | None,
    custom_character_id: str | None,
    user_id: str,
) -> dict:
    """DB에 GENERATING 상태 콘티를 생성하고 ``{"id": ...}`` 를 반환한다."""
    record = await db.storyboard.create(
        data={
            "idea": idea,
            "characterId": character_id,
            "customCharacterId": custom_character_id,
            "userId": user_id,
        }
    )
    return {"id": record.id}


async def list_storyboards(user_id: str) -> list:
    """유저의 콘티 목록을 반환한다 (scenes 포함, createdAt 내림차순, 최대 50개)."""
    return await db.storyboard.find_many(
        where={"userId": user_id},
        order={"createdAt": "desc"},
        take=50,
        include={"scenes": True},
    )


async def get_storyboard_detail(
    storyboard_id: str,
    user_id: str,
) -> object | None:
    """콘티 상세 조회 (scenes + 연결된 프로젝트 포함). 없거나 소유권 불일치 시 None."""
    return await db.storyboard.find_first(
        where={"id": storyboard_id, "userId": user_id},
        include={"scenes": True, "project": True},
    )


async def update_scene(
    storyboard_id: str,
    scene_id: str,
    user_id: str,
    *,
    title: str | None = None,
    content: str | None = None,
) -> object:
    """장면 제목/내용 수정. content 변경 시 imageStatus → STALE.

    소유권 불일치·장면 없음·수정 내용 없음 시 ``ValueError`` 를 발생시킨다.
    """
    sb = await db.storyboard.find_first(
        where={"id": storyboard_id, "userId": user_id},
    )
    if not sb:
        raise ValueError("콘티를 찾을 수 없습니다")

    scene = await db.storyboardscene.find_first(
        where={"id": scene_id, "storyboardId": storyboard_id},
    )
    if not scene:
        raise ValueError("장면을 찾을 수 없습니다")

    update_data: dict = {}
    if title is not None:
        update_data["title"] = title
    if content is not None:
        update_data["content"] = content
        if scene.imageStatus == "COMPLETED":
            update_data["imageStatus"] = "STALE"

    if not update_data:
        raise ValueError("수정할 내용이 없습니다")

    return await db.storyboardscene.update(
        where={"id": scene_id},
        data=update_data,
    )


async def get_scene_for_regenerate(
    storyboard_id: str,
    scene_id: str,
    user_id: str,
) -> object:
    """이미지 재생성 전 장면 조회 + 소유권 확인 + GENERATING 중복 방어.

    실패 시 ``ValueError`` 를 발생시킨다.
    """
    sb = await db.storyboard.find_first(
        where={"id": storyboard_id, "userId": user_id},
    )
    if not sb:
        raise ValueError("콘티를 찾을 수 없습니다")

    scene = await db.storyboardscene.find_first(
        where={"id": scene_id, "storyboardId": storyboard_id},
    )
    if not scene:
        raise ValueError("장면을 찾을 수 없습니다")

    if scene.imageStatus == "GENERATING":
        raise ValueError("이미 이미지를 생성하고 있습니다")

    return scene


async def get_storyboard_for_video(
    storyboard_id: str,
    user_id: str,
) -> object:
    """영상 생성용 콘티 조회 + 상태 검증 + 이미지 완성 확인.

    실패 시 ``ValueError`` 를 발생시킨다.
    """
    record = await db.storyboard.find_first(
        where={"id": storyboard_id, "userId": user_id},
        include={"scenes": True},
    )
    if not record:
        raise ValueError("콘티를 찾을 수 없습니다")

    if record.status == "VIDEO_GENERATING":
        raise ValueError("이미 영상을 생성하고 있습니다")

    if record.status not in ("READY", "VIDEO_READY"):
        raise ValueError("콘티가 준비되지 않았습니다 (이미지 생성 완료 필요)")

    scenes = record.scenes or []
    incomplete = [s for s in scenes if s.imageStatus != "COMPLETED"]
    if incomplete:
        raise ValueError(f"{len(incomplete)}개 장면의 이미지가 아직 완성되지 않았습니다")

    return record


# ── WebSocket 핸들러용 DB 조회 함수 ──


async def get_storyboard_status(
    storyboard_id: str,
    user_id: str,
) -> dict | None:
    """WS용 콘티 상태 조회. 없거나 소유권 불일치 시 None."""
    record = await db.storyboard.find_first(
        where={"id": storyboard_id, "userId": user_id},
    )
    if not record:
        return None

    status = record.status
    progress = 100 if status == "READY" else (0 if status == "GENERATING" else -1)
    return {
        "id": storyboard_id,
        "progress": max(progress, 0),
        "step": (
            "완료" if status == "READY" else ("생성 중" if status == "GENERATING" else "실패")
        ),
        "status": status,
    }


async def get_storyboard_video_status(
    storyboard_id: str,
    user_id: str,
) -> dict | None:
    """WS용 영상 생성 진행률 조회. 없거나 소유권 불일치 시 None."""
    record = await db.storyboard.find_first(
        where={"id": storyboard_id, "userId": user_id},
        include={"scenes": True},
    )
    if not record:
        return None

    scenes = sorted(record.scenes or [], key=lambda s: s.sceneOrder)
    total = len(scenes)
    done = sum(1 for s in scenes if s.videoStatus in ("COMPLETED", "FAILED"))
    overall = int((done / total) * 100) if total > 0 else 0

    return {
        "storyboard_id": storyboard_id,
        "status": record.status,
        "overall_progress": overall,
        "estimated_remaining_seconds": 0,
        "final_video_url": record.finalVideoUrl,
        "scenes": [
            {
                "id": s.id,
                "scene_order": s.sceneOrder,
                "video_status": s.videoStatus,
                "video_url": s.videoUrl,
                "error": s.videoError,
            }
            for s in scenes
        ],
    }


async def get_scene_image_status(
    scene_id: str,
    user_id: str,
) -> dict | None:
    """WS용 장면 이미지 상태 조회. 소유권 불일치/장면 없음 시 None."""
    scene = await db.storyboardscene.find_unique(
        where={"id": scene_id},
        include={"storyboard": True},
    )
    if not scene or not scene.storyboard:
        return None
    if scene.storyboard.userId != user_id:
        return None

    img_status = scene.imageStatus
    progress = (
        100 if img_status == "COMPLETED" else (0 if img_status in ("GENERATING", "PENDING") else -1)
    )
    return {
        "id": scene_id,
        "progress": max(progress, 0),
        "step": (
            "완료"
            if img_status == "COMPLETED"
            else ("생성 중" if img_status == "GENERATING" else "실패")
        ),
        "status": img_status,
    }
