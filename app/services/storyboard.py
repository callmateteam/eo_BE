"""콘티 생성 서비스 - GPT 장면 분할 + GPT 이미지 생성 (Veo 시작 프레임 겸용)"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from collections.abc import Awaitable, Callable

import httpx

from app.core.config import settings
from app.core.database import db
from app.core.s3 import upload_image
from app.services.tts import generate_scene_narrations

logger = logging.getLogger(__name__)

# ── GPT 콘티 생성 프롬프트 (토큰 최적화) ──

STORYBOARD_SYSTEM = """\
Short-form video storyboard creator for image-to-video pipeline.
Create scene cuts from character + idea.

Rules:
- Total ≤ 60s, each scene 3-10s
- Output ONLY valid JSON array
- 3-5 scenes (strictly, never more than 5)
- imagePrompt: English, max 40 words. Describe a STATIC opening \
freeze-frame (NOT motion): (1) character POSE/POSITION, \
(2) background/location matching world context, (3) key props. \
The character should be in a natural starting pose with room for \
implied motion. NO text/letters/words in the image.
- motionPrompt: English, max 30 words. Describe ONLY the motion/action \
that should happen in this scene. Do NOT repeat what's visible in \
the image. Focus on: movement direction, speed, gestures, expressions.
- title/content: Korean, concise
- duration: action=short, dialogue=longer
- hasCharacter: true if the character appears in this scene
- secondaryCharacter: name of another character (null if none). \
Only if the idea mentions another character by name.
- narration: Korean TTS text. null if silent
- narrationStyle: "character"|"narrator"|"none"
- bgmMood: overall BGM mood (first scene only): \
epic/funny/calm/tense/sad/upbeat/mysterious
- Vary visual composition: mix close-ups, medium, wide shots across scenes.

[{"title":"","content":"","imagePrompt":"","motionPrompt":"",\
"duration":5.0,"hasCharacter":true,"secondaryCharacter":null,\
"narration":"","narrationStyle":"character","bgmMood":"funny"}]"""

STORYBOARD_USER = """\
캐릭터: {character_desc}
세계관/배경: {world_context}
아트 스타일: {art_style}
아이디어: {idea}
60초 이내 숏폼 콘티 생성. 배경은 세계관에 맞게 구성."""

# 이미지 동시 요청 제한 (rate limit 방지) - 지연 초기화
_IMAGE_SEMAPHORE: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
    """이벤트 루프 시작 후 세마포어 지연 생성"""
    global _IMAGE_SEMAPHORE  # noqa: PLW0603
    if _IMAGE_SEMAPHORE is None:
        _IMAGE_SEMAPHORE = asyncio.Semaphore(3)
    return _IMAGE_SEMAPHORE


async def generate_scenes_with_gpt(
    character_desc: str,
    idea: str,
    *,
    world_context: str = "",
    art_style: str = "",
) -> tuple[list[dict], str | None]:
    """GPT-4o-mini로 콘티 장면 분할 생성 (토큰 절약)"""
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "gpt-4o-mini",
                "max_tokens": 2000,
                "temperature": 0.7,
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
                        ),
                    },
                ],
            },
        )
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"].strip()
        parsed = json.loads(raw)

        # response_format=json_object는 객체를 반환하므로 배열 추출
        if isinstance(parsed, list):
            scenes = parsed
        else:
            # GPT가 사용할 수 있는 다양한 키 처리
            for key in ("scenes", "data", "storyboard", "cuts"):
                if key in parsed and isinstance(parsed[key], list):
                    scenes = parsed[key]
                    break
            else:
                scenes = []

        if not scenes:
            raise ValueError("GPT가 유효한 장면을 생성하지 못했습니다")

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
            narration_style = str(s.get("narrationStyle", "none"))
            if narration_style not in ("character", "narrator", "none"):
                narration_style = "none"
            # narration이 없으면 style도 none으로 통일
            if not narration:
                narration_style = "none"

            validated.append(
                {
                    "title": str(s.get("title", "장면"))[:100],
                    "content": str(s.get("content", ""))[:2000],
                    "imagePrompt": str(s.get("imagePrompt", ""))[:200],
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
    reference_image_bytes: bytes | None = None,
    art_style: str = "",
    world_context: str = "",
    bgm_mood: str | None = None,
) -> tuple[str, bytes]:
    """GPT 이미지 생성으로 장면 시작 프레임 생성 → S3 업로드

    캐릭터 일관성을 최우선으로:
    - 캐릭터 외형 설명 고정 (veoPrompt/promptFeatures)
    - reference_image_bytes가 있으면 edits API 사용
    - 아트 스타일은 캐릭터 데이터에서 동적 결정
    """

    # 스타일: 캐릭터 데이터 기반 (하드코딩 제거)
    if art_style:
        style_text = art_style
    else:
        style_text = "Japanese anime style, hand-drawn cel animation look"

    # 조명: 분위기 기반
    mood_lighting = {
        "epic": "dramatic golden hour lighting with lens flare",
        "funny": "bright cheerful lighting with vibrant colors",
        "calm": "soft natural lighting with warm tones",
        "tense": "low-key dramatic lighting with deep shadows",
        "sad": "overcast muted lighting with cool blue tones",
        "mysterious": "moody atmospheric lighting with fog",
    }
    lighting = mood_lighting.get(bgm_mood or "", "natural lighting")

    # 배경 컨텍스트
    bg_text = ""
    if world_context:
        bg_text = f"Background setting: {world_context.split(',')[0].strip()}. "

    full_prompt = (
        f"{character_desc}. "
        f"Scene: {image_prompt}. "
        f"{bg_text}"
        f"{style_text}. {lighting}. "
        "The character is in a natural starting pose with room for "
        "implied motion, NOT mid-action. "
        "Keep the character's appearance EXACTLY consistent: same face, "
        "same hair, same outfit, same proportions as described. "
        "CRITICAL: Do not render any text, letters, or written characters. "
        "Replace any text with symbols or abstract patterns."
    )[:4000]

    async with _get_semaphore():
        if reference_image_bytes:
            img_data = await _generate_with_edit(full_prompt, reference_image_bytes)
        else:
            img_data = await _generate_new(full_prompt)

    s3_url = await asyncio.to_thread(
        upload_image,
        img_data,
        user_id,
        content_type="image/png",
        folder="storyboard-scenes",
    )
    return s3_url, img_data


async def _generate_new(prompt: str) -> bytes:
    """새 이미지 생성 (generations API)"""
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            "https://api.openai.com/v1/images/generations",
            headers={
                "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "gpt-image-1",
                "prompt": prompt,
                "n": 1,
                "size": "1024x1536",
                "quality": "medium",
            },
        )
        resp.raise_for_status()
        result = resp.json()["data"][0]

    if "b64_json" in result:
        return base64.b64decode(result["b64_json"])

    async with httpx.AsyncClient(timeout=60) as client:
        img_resp = await client.get(result["url"])
        img_resp.raise_for_status()
        return img_resp.content


async def _generate_with_edit(prompt: str, reference_bytes: bytes) -> bytes:
    """히어로 프레임을 참조하여 편집 API로 캐릭터 일관성 유지 (multipart/form-data)"""
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            "https://api.openai.com/v1/images/edits",
            headers={
                "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
            },
            data={
                "model": "gpt-image-1",
                "prompt": prompt,
                "n": "1",
                "size": "1024x1024",
                "quality": "medium",
            },
            files={
                "image": ("reference.png", reference_bytes, "image/png"),
            },
        )
        resp.raise_for_status()
        result = resp.json()["data"][0]

    if "b64_json" in result:
        return base64.b64decode(result["b64_json"])

    async with httpx.AsyncClient(timeout=60) as client:
        img_resp = await client.get(result["url"])
        img_resp.raise_for_status()
        return img_resp.content


class CharacterInfo:
    """캐릭터 설명 + 음성 설정 + 원본 이미지 + 세계관/스타일"""

    def __init__(
        self,
        description: str,
        voice_id: str,
        voice_style: str,
        image_url: str | None = None,
        world_context: str = "",
        art_style: str = "",
    ) -> None:
        self.description = description
        self.voice_id = voice_id
        self.voice_style = voice_style
        self.image_url = image_url
        self.world_context = world_context
        self.art_style = art_style


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
            world_context="",
            art_style=style_prompt,
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
        async with httpx.AsyncClient(timeout=15) as client:
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

        # Step 3: S3 원본 이미지 자동 선택 (DALL-E 제거, 비용 $0)
        from app.services.prompt_optimizer import detect_scene_type, select_best_image

        db_scenes = await db.storyboardscene.find_many(
            where={"storyboardId": storyboard_id},
            order={"sceneOrder": "asc"},
        )

        # 캐릭터 시드 데이터 조회 (extraImages, artStyle 등)
        sb_for_char = await db.storyboard.find_unique(
            where={"id": storyboard_id},
            include={"character": True},
        )
        extra_images = ""
        base_image_url = character_image_url or ""
        if sb_for_char and sb_for_char.character:
            c = sb_for_char.character
            extra_images = getattr(c, "extraImages", "") or ""
            base_image_url = c.imageUrl or base_image_url

        await notify(45, "장면별 이미지 선택 중...")

        for sc in db_scenes:
            try:
                # 장면 유형 감지 → 최적 S3 이미지 자동 선택
                scene_type = detect_scene_type(sc.content, getattr(sc, "imagePrompt", None))
                selected_url = select_best_image(
                    extra_images=extra_images,
                    scene_type=scene_type,
                    base_image_url=base_image_url,
                )
                await db.storyboardscene.update(
                    where={"id": sc.id},
                    data={"imageUrl": selected_url, "imageStatus": "COMPLETED"},
                )
                logger.info(
                    "장면 %d: type=%s → %s",
                    sc.sceneOrder,
                    scene_type,
                    selected_url.split("/")[-1],
                )
            except Exception:
                logger.exception("장면 이미지 선택 실패: %s", sc.id)
                await db.storyboardscene.update(
                    where={"id": sc.id},
                    data={
                        "imageUrl": base_image_url,
                        "imageStatus": "COMPLETED",
                    },
                )

        # 히어로 프레임 = 첫 장면 이미지
        if db_scenes:
            first_scene = await db.storyboardscene.find_first(
                where={"storyboardId": storyboard_id},
                order={"sceneOrder": "asc"},
            )
            if first_scene and first_scene.imageUrl:
                await db.storyboard.update(
                    where={"id": storyboard_id},
                    data={"heroFrameUrl": first_scene.imageUrl},
                )

        await notify(55, "이미지 선택 완료")

        # Step 4: TTS 나레이션 생성 (90-95%)
        await notify(90, "나레이션 음성 생성 중...")
        db_scenes_for_tts = await db.storyboardscene.find_many(
            where={"storyboardId": storyboard_id},
            order={"sceneOrder": "asc"},
        )
        await generate_scene_narrations(
            scenes=db_scenes_for_tts,
            voice_id=voice_id,
            voice_style=voice_style,
            user_id=user_id,
        )

        # Step 5: 완료 여부 확인 (95-100%)
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
) -> str:
    """콘티 설명(한글)을 이미지 생성용 영문 프롬프트로 변환"""
    async with httpx.AsyncClient(timeout=30) as client:
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
                            "Convert Korean scene description to "
                            "English image prompt. Max 20 words. "
                            "Opening shot only. No style/format words. "
                            "NEVER include text/letters/words. Use symbols or gestures instead."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (f"캐릭터: {character_desc}\n장면 설명: {content}"),
                    },
                ],
            },
        )
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"].strip()
        # 20단어 초과 시 잘라냄
        words = raw.split()
        if len(words) > 20:
            raw = " ".join(words[:20]).rstrip(",")
        return raw


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

        # 현재 content 기반으로 새 imagePrompt 생성
        new_prompt = await content_to_image_prompt(scene.content, character_desc)
        await notify(35, "이미지 프롬프트 생성 완료")

        await notify(45, "AI가 시작 프레임을 생성하고 있습니다...")
        s3_url, _ = await generate_scene_image(new_prompt, character_desc, user_id)

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
