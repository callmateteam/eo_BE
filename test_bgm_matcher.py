"""BGM 매칭 서비스 로컬 테스트 (DB 없이)"""

import asyncio
import json
import os
import sys

# 프로젝트 루트를 path에 추가
sys.path.insert(0, os.path.dirname(__file__))

from app.services.bgm_matcher import _summarize_profile, _describe_scenes


def load_profile_from_seed_sql(preset_name: str) -> list[dict]:
    """seed SQL에서 에너지 프로파일 추출"""
    sql_path = os.path.join(
        os.path.dirname(__file__), "prisma", "migrations", "seed_bgm_presets.sql"
    )
    with open(sql_path, encoding="utf-8") as f:
        content = f.read()

    # 해당 프리셋의 INSERT 문 찾기
    marker = f"'{preset_name}'"
    idx = content.find(marker)
    if idx == -1:
        return []

    # JSON 배열 추출 ('{' 시작 ~ '}]'::jsonb 끝)
    json_start = content.find("'[{", idx)
    json_end = content.find("}]'", json_start)
    if json_start == -1 or json_end == -1:
        return []

    json_str = content[json_start + 1 : json_end + 2]
    return json.loads(json_str)


def test_summarize_profile():
    """프로파일 요약 테스트"""
    print("=" * 60)
    print("1. 프로파일 요약 테스트")
    print("=" * 60)

    for preset in ["horror", "calm", "epic", "funny"]:
        profile = load_profile_from_seed_sql(preset)
        if not profile:
            print(f"  [{preset}] 프로파일 로드 실패")
            continue

        summary = _summarize_profile(profile)
        print(f"\n  [{preset}] ({len(profile)}초)")
        print(f"  {summary}")


def test_describe_scenes():
    """씬 설명 테스트"""
    print("\n" + "=" * 60)
    print("2. 씬 설명 테스트")
    print("=" * 60)

    scenes = [
        {"content": "어두운 골목에서 주인공이 뒤를 돌아본다", "duration": 5.0, "narration": "뭔가 이상한 느낌이 들었다", "mood": "tense"},
        {"content": "갑자기 그림자가 벽을 타고 다가온다", "duration": 4.0, "narration": None, "mood": "horror"},
        {"content": "주인공이 전력으로 달리기 시작한다", "duration": 5.0, "narration": "도망쳐야 해!", "mood": "action"},
    ]
    desc = _describe_scenes(scenes)
    print(f"\n{desc}")


async def test_gpt_recommendation():
    """GPT 시작지점 추천 테스트 (OpenAI API 직접 호출)"""
    print("\n" + "=" * 60)
    print("3. GPT 시작지점 추천 테스트")
    print("=" * 60)

    import httpx

    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        # .env에서 로드
        env_path = os.path.join(os.path.dirname(__file__), ".env")
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    if line.startswith("OPENAI_API_KEY="):
                        api_key = line.strip().split("=", 1)[1]
                        break

    if not api_key:
        print("  OPENAI_API_KEY 없음 — GPT 테스트 건너뜀")
        return

    from app.services.bgm_matcher import BGM_MATCH_SYSTEM, BGM_MATCH_USER

    # horror 프로파일 로드 + 테스트 씬
    profile = load_profile_from_seed_sql("horror")
    summary = _summarize_profile(profile)

    scenes = [
        {"content": "어두운 골목에서 주인공이 뒤를 돌아본다", "duration": 5.0, "narration": "뭔가 이상한 느낌이 들었다"},
        {"content": "갑자기 그림자가 벽을 타고 다가온다", "duration": 4.0, "narration": None},
        {"content": "주인공이 전력으로 달리기 시작한다", "duration": 5.0, "narration": "도망쳐야 해!"},
    ]
    scenes_desc = _describe_scenes(scenes)
    total_duration = sum(s["duration"] for s in scenes)

    user_msg = BGM_MATCH_USER.format(
        preset_name="horror",
        display_name="공포",
        duration=65.2,
        profile_summary=summary,
        total_duration=total_duration,
        scenes_desc=scenes_desc,
    )

    print(f"\n  [요청 메시지]\n{user_msg}\n")

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
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
        result = json.loads(text)

        print(f"  [GPT 응답]")
        print(f"  시작지점: {result['start_time']}초")
        print(f"  이유: {result['reason']}")

    # epic으로도 테스트
    profile2 = load_profile_from_seed_sql("epic")
    summary2 = _summarize_profile(profile2)

    scenes2 = [
        {"content": "거대한 성문이 열리며 군대가 전진한다", "duration": 5.0, "narration": "전쟁이 시작됐다"},
        {"content": "하늘에서 드래곤이 불을 내뿜는다", "duration": 4.0, "narration": None},
        {"content": "영웅이 검을 들어올리며 돌격 명령을 내린다", "duration": 5.0, "narration": "지금이다!"},
    ]
    scenes_desc2 = _describe_scenes(scenes2)

    user_msg2 = BGM_MATCH_USER.format(
        preset_name="epic",
        display_name="웅장한",
        duration=96.0,
        profile_summary=summary2,
        total_duration=sum(s["duration"] for s in scenes2),
        scenes_desc=scenes_desc2,
    )

    print(f"\n  [epic 테스트]")
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "gpt-4o-mini",
                "temperature": 0.3,
                "max_tokens": 200,
                "messages": [
                    {"role": "system", "content": BGM_MATCH_SYSTEM},
                    {"role": "user", "content": user_msg2},
                ],
            },
        )
        resp.raise_for_status()
        data = resp.json()
        text = data["choices"][0]["message"]["content"].strip()
        result2 = json.loads(text)
        print(f"  시작지점: {result2['start_time']}초")
        print(f"  이유: {result2['reason']}")


def test_ffmpeg_cmd():
    """ffmpeg 명령어 생성 테스트"""
    print("\n" + "=" * 60)
    print("4. ffmpeg 명령어 생성 테스트")
    print("=" * 60)

    from app.services.video_merge import _build_bgm_mix_cmd

    # 시작지점 0 (기본)
    cmd1 = _build_bgm_mix_cmd("input.mp4", "bgm.mp3", "output.mp4", has_tts=True)
    has_ss = "-ss" in cmd1
    print(f"\n  [기본] -ss 포함: {has_ss} (기대: False)")

    # 시작지점 20초
    cmd2 = _build_bgm_mix_cmd("input.mp4", "bgm.mp3", "output.mp4", has_tts=True, bgm_start_time=20.0)
    ss_idx = cmd2.index("-ss") if "-ss" in cmd2 else -1
    ss_val = cmd2[ss_idx + 1] if ss_idx >= 0 else None
    print(f"  [20초] -ss 값: {ss_val} (기대: 20.0)")

    # 페이드인 확인
    fc_idx = cmd2.index("-filter_complex") + 1
    fc = cmd2[fc_idx]
    has_fadein = "afade=t=in" in fc
    has_ducking = "sidechaincompress" in fc
    print(f"  페이드인: {has_fadein} (기대: True)")
    print(f"  덕킹: {has_ducking} (기대: True)")

    # TTS 없는 경우
    cmd3 = _build_bgm_mix_cmd("input.mp4", "bgm.mp3", "output.mp4", has_tts=False, bgm_start_time=10.0)
    fc3 = cmd3[cmd3.index("-filter_complex") + 1]
    no_ducking = "sidechaincompress" not in fc3
    print(f"  [TTS없음] 덕킹 없음: {no_ducking} (기대: True)")


if __name__ == "__main__":
    test_summarize_profile()
    test_describe_scenes()
    test_ffmpeg_cmd()
    asyncio.run(test_gpt_recommendation())
    print("\n" + "=" * 60)
    print("전체 테스트 완료!")
    print("=" * 60)
