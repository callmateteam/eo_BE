"""BGM 시작지점 추천 서비스

에너지 프로파일 기반으로 GPT가 씬 묶음에 적합한 BGM 시작 구간을 추천한다.
BGM은 시작지점부터 연속 재생되며, TTS 구간에서는 사이드체인 덕킹이 자동 적용된다.
"""

from __future__ import annotations

import json
import logging

from app.core.config import settings
from app.core.database import db
from app.core.http_client import get_openai_client

logger = logging.getLogger(__name__)

# GPT 시스템 프롬프트
BGM_MATCH_SYSTEM = """\
You are a professional music editor for short-form vertical videos.
Given a BGM energy profile and scene descriptions, recommend the best START TIME (in seconds) \
for the BGM track so it plays continuously across all scenes.

Rules:
- The BGM plays from start_time for the total_duration of all scenes combined.
- Pick a start_time where the energy/mood matches the scene flow.
- If scenes start calm and build tension, pick a start_time at a quiet section so the music \
naturally builds.
- If scenes are all high energy, pick a start_time at a loud/climax section.
- If the BGM is shorter than needed, it will loop — prefer start points that loop naturally.
- Consider fade-in at the start and sidechain ducking when TTS narration is present.
- NEVER start at the very last 3 seconds (fade-out zone).

Respond with ONLY a JSON object:
{"start_time": <float>, "reason": "<1-line Korean explanation>"}"""

BGM_MATCH_USER = """\
BGM 프리셋: {preset_name} ({display_name})
BGM 길이: {duration}초
에너지 프로파일 (1초 단위):
{profile_summary}

씬 목록 (총 {total_duration}초):
{scenes_desc}"""


async def get_bgm_preset(name: str) -> dict | None:
    """DB에서 BGM 프리셋 조회"""
    preset = await db.bgmpreset.find_unique(where={"name": name})
    if not preset:
        return None
    return {
        "name": preset.name,
        "display_name": preset.displayName,
        "s3_key": preset.s3Key,
        "duration": preset.duration,
        "integrated_lufs": preset.integratedLufs,
        "energy_profile": preset.energyProfile,
    }


async def get_all_bgm_presets() -> list[dict]:
    """모든 BGM 프리셋 목록 (에너지 프로파일 제외)"""
    presets = await db.bgmpreset.find_many(order={"name": "asc"})
    return [
        {
            "name": p.name,
            "display_name": p.displayName,
            "s3_key": p.s3Key,
            "duration": p.duration,
        }
        for p in presets
    ]


def _summarize_profile(energy_profile: list[dict]) -> str:
    """에너지 프로파일을 GPT에게 보낼 요약 형태로 변환

    전체를 보내면 토큰이 너무 많으므로, 구간별 요약으로 압축한다.
    """
    if not energy_profile:
        return "프로파일 없음"

    sections: list[dict] = []
    prev_label = None
    start_t = 0

    for p in energy_profile:
        label = p.get("label", "unknown")
        if label != prev_label:
            if prev_label is not None:
                sections.append({"start": start_t, "end": p["t"], "label": prev_label})
            start_t = p["t"]
            prev_label = label
    # 마지막 구간
    if prev_label is not None:
        sections.append({
            "start": start_t,
            "end": energy_profile[-1]["t"] + 1,
            "label": prev_label,
        })

    # 연속 같은 레이블 합치기
    merged: list[dict] = []
    for s in sections:
        if merged and merged[-1]["label"] == s["label"]:
            merged[-1]["end"] = s["end"]
        else:
            merged.append(dict(s))

    lines = []
    for s in merged:
        dur = s["end"] - s["start"]
        if dur >= 2:
            lines.append(f"  {s['start']}s~{s['end']}s: {s['label']} ({dur}초)")
    return "\n".join(lines) if lines else "전체 일정"


def _describe_scenes(scenes: list[dict]) -> str:
    """씬 목록을 텍스트로 변환"""
    lines = []
    for i, s in enumerate(scenes, 1):
        dur = s.get("duration", 5.0)
        content = s.get("content", "")[:80]
        mood = s.get("mood", "")
        has_tts = bool(s.get("narration"))
        tts_marker = " [TTS]" if has_tts else ""
        lines.append(f"  씬{i} ({dur}초){tts_marker}: {content}")
        if mood:
            lines[-1] += f" (분위기: {mood})"
    return "\n".join(lines)


async def recommend_bgm_start(
    preset_name: str,
    scenes: list[dict],
) -> dict:
    """GPT를 사용하여 BGM 시작 지점 추천

    Args:
        preset_name: BGM 프리셋 이름 (e.g., "horror")
        scenes: 씬 목록 [{"content": "...", "duration": 5.0, "narration": "...", "mood": ""}]

    Returns:
        {"start_time": float, "reason": str, "preset": dict}
    """
    preset = await get_bgm_preset(preset_name)
    if not preset:
        logger.warning("BGM 프리셋 없음: %s, 0초부터 시작", preset_name)
        return {"start_time": 0.0, "reason": "프리셋 없음 — 처음부터 재생", "preset": None}

    total_duration = sum(s.get("duration", 5.0) for s in scenes)
    profile_summary = _summarize_profile(preset["energy_profile"])
    scenes_desc = _describe_scenes(scenes)

    user_msg = BGM_MATCH_USER.format(
        preset_name=preset["name"],
        display_name=preset["display_name"],
        duration=preset["duration"],
        profile_summary=profile_summary,
        total_duration=round(total_duration, 1),
        scenes_desc=scenes_desc,
    )

    client = get_openai_client()
    try:
        resp = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "gpt-4o-mini",
                "temperature": 0.3,
                "max_tokens": 200,
                "messages": [
                    {"role": "system", "content": BGM_MATCH_SYSTEM},
                    {"role": "user", "content": user_msg},
                ],
            },
        )
        resp.raise_for_status()
        data = resp.json()
        text = data["choices"][0]["message"]["content"].strip()

        # JSON 파싱
        result = json.loads(text)
        start_time = float(result.get("start_time", 0.0))
        reason = result.get("reason", "")

        # 유효성 검증: BGM 길이 내, 마지막 3초 이전
        max_start = max(0, preset["duration"] - 3)
        start_time = max(0.0, min(start_time, max_start))

        logger.info(
            "BGM 매칭: %s → %.1fs부터 (씬 %d개, 총 %.1fs) — %s",
            preset_name, start_time, len(scenes), total_duration, reason,
        )

        return {
            "start_time": round(start_time, 1),
            "reason": reason,
            "preset": preset,
        }

    except Exception:
        logger.exception("BGM 매칭 GPT 호출 실패, 0초부터 시작")
        return {
            "start_time": 0.0,
            "reason": "GPT 호출 실패 — 처음부터 재생",
            "preset": preset,
        }


def get_bgm_s3_url(s3_key: str) -> str:
    """S3 키로 BGM URL 생성"""
    bucket = settings.S3_BUCKET
    region = settings.AWS_REGION
    return f"https://{bucket}.s3.{region}.amazonaws.com/{s3_key}"
