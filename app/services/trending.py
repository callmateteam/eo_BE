"""트렌딩 키워드 서비스 - Google Trends + YouTube Trending → GPT 필터링"""

from __future__ import annotations

import json
import logging
import re
import time
from urllib.parse import quote

import httpx
from defusedxml import ElementTree

from app.core.config import settings

logger = logging.getLogger(__name__)

_HANGUL_RE = re.compile(r"[가-힣]")

GOOGLE_TRENDS_RSS = "https://trends.google.co.kr/trending/rss?geo=KR"
YOUTUBE_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"

# 캐시
_raw_cache: dict[str, object] = {"data": None, "expires_at": 0.0}
_filtered_cache: dict[str, object] = {"data": None, "expires_at": 0.0}
RAW_CACHE_TTL = 600  # 원본 10분
FILTERED_CACHE_TTL = 900  # 필터링 결과 15분

# YouTube 카테고리 (한국)
# 1=영화/애니, 20=게임, 22=인물/블로그, 24=엔터테인먼트, 25=뉴스, 26=스타일
_YT_CATEGORY_NAMES: dict[str, str] = {
    "1": "영화/애니",
    "10": "음악",
    "20": "게임",
    "22": "블로그",
    "24": "엔터테인먼트",
    "25": "뉴스",
    "26": "스타일",
}

# ── GPT 필터링 프롬프트 ──

_FILTER_SYSTEM = """\
너는 애니 캐릭터 숏폼 콘텐츠 플랫폼의 트렌드 키워드 큐레이터야.

우리 플랫폼: 애니 캐릭터(루피, 짱구, 나루토 등)로 숏폼 영상을 만드는 서비스.
사용자가 키워드를 보고 바로 "이 캐릭터로 이 영상 만들어야지!" 할 수 있어야 해.

핵심 규칙:
1. 반드시 "애니 캐릭터명 + 행동/음식" 형태로 만들어
2. 트렌드에서 쓸만한 주제(애니, 음식, 계절, 게임)만 영감으로 활용해
3. 부적합한 트렌드(정치, 주식, 인물 뉴스 등)는 완전히 무시하고
   대신 현재 계절/시기에 맞는 아이디어를 직접 만들어
4. 실존 인물 이름은 절대 포함하지 마

좋은 예시:
- "멜리오다스 풀코스 요리" (애니 트렌드 → 캐릭터 활용)
- "짱구 두쫀쿠 먹방" (음식 트렌드 → 캐릭터가 먹기)
- "루피 봄동 비빔밥 요리" (계절 음식)
- "나루토 벚꽃 소풍" (계절 이벤트)
- "쵸파 마인크래프트 건축" (게임 트렌드)

형식:
- 3-6단어, 한글만, 이모지 금지
- 반드시 5개, 캐릭터 중복 최소화
- JSON 배열만 반환"""

_FILTER_USER = """\
현재 트렌딩 키워드:
{keywords_json}

위 트렌드를 참고해서 "캐릭터명 + 행동/상황" 형태 키워드 5개를 만들어줘."""


async def fetch_trending_keywords(max_results: int = 5) -> list[dict]:
    """Google Trends + YouTube Trending → GPT 필터링 → 상위 N개 반환"""
    now = time.time()

    # 필터링 캐시 확인
    if _filtered_cache["data"] and now < _filtered_cache["expires_at"]:
        cached = _filtered_cache["data"]
        return cached[:max_results]  # type: ignore[index]

    try:
        # 1. 두 소스에서 키워드 수집
        raw_keywords = await _collect_all_keywords()
        if not raw_keywords:
            return []

        # 2. GPT 필터링
        filtered = await _filter_keywords_gpt(raw_keywords)

        # 3. YouTube 조회수 조회 + 정렬
        filtered = await _enrich_with_views(filtered)

        # 4. 캐시 저장
        _filtered_cache["data"] = filtered
        _filtered_cache["expires_at"] = now + FILTERED_CACHE_TTL

        return filtered[:max_results]
    except Exception:
        logger.exception("트렌딩 키워드 조회/필터링 실패")
        raw = _raw_cache.get("data") or []
        return raw[:max_results]  # type: ignore[index]


async def _collect_all_keywords() -> list[dict]:
    """Google Trends + YouTube Trending 키워드 통합 수집"""
    now = time.time()
    if _raw_cache["data"] and now < _raw_cache["expires_at"]:
        return _raw_cache["data"]  # type: ignore[return-value]

    # 두 소스 병렬 수집
    import asyncio

    google_task = asyncio.create_task(_fetch_google_trends())
    youtube_task = asyncio.create_task(_fetch_youtube_trending())

    google_results = await google_task
    youtube_results = await youtube_task

    # 중복 제거 (키워드 기준)
    seen: set[str] = set()
    combined: list[dict] = []

    for item in google_results + youtube_results:
        kw = item["keyword"]
        if kw not in seen:
            seen.add(kw)
            combined.append(item)

    # rank 재부여
    for i, r in enumerate(combined):
        r["rank"] = i + 1

    logger.info(
        "키워드 수집: Google %d개 + YouTube %d개 → 통합 %d개",
        len(google_results),
        len(youtube_results),
        len(combined),
    )

    _raw_cache["data"] = combined
    _raw_cache["expires_at"] = now + RAW_CACHE_TTL

    return combined


async def _fetch_google_trends() -> list[dict]:
    """Google Trends RSS 피드에서 한국 인기 검색어 파싱"""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(GOOGLE_TRENDS_RSS)
            resp.raise_for_status()

        root = ElementTree.fromstring(resp.text)
        items = root.findall(".//item")

        ht_ns = "https://trends.google.com/trending/rss"

        results: list[dict] = []
        for item in items:
            title = item.findtext("title", "").strip()
            traffic = item.findtext(f"{{{ht_ns}}}approx_traffic", "").strip()

            if not title or not _HANGUL_RE.search(title):
                continue

            results.append(
                {
                    "keyword": title,
                    "traffic": traffic,
                    "source": "google",
                }
            )

        results.sort(key=lambda x: _parse_traffic(x["traffic"]), reverse=True)
        return results

    except Exception:
        logger.exception("Google Trends 조회 실패")
        return []


async def _fetch_youtube_trending() -> list[dict]:
    """YouTube Data API v3로 한국 인기 동영상 제목에서 키워드 추출"""
    api_key = settings.YOUTUBE_API_KEY or settings.GOOGLE_API_KEY
    if not api_key:
        logger.warning("YouTube API 키 없음, 스킵")
        return []

    try:
        params = {
            "part": "snippet",
            "chart": "mostPopular",
            "regionCode": "KR",
            "maxResults": 50,
            "key": api_key,
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(YOUTUBE_VIDEOS_URL, params=params)
            resp.raise_for_status()
            data = resp.json()

        results: list[dict] = []
        seen_titles: set[str] = set()

        for item in data.get("items", []):
            snippet = item.get("snippet", {})
            title = snippet.get("title", "").strip()
            category_id = snippet.get("categoryId", "")
            channel = snippet.get("channelTitle", "")

            if not title:
                continue

            # 키워드 추출: 제목을 정리
            keyword = _extract_keyword_from_title(title)
            if not keyword or keyword in seen_titles:
                continue
            seen_titles.add(keyword)

            category_name = _YT_CATEGORY_NAMES.get(category_id, "기타")

            results.append(
                {
                    "keyword": keyword,
                    "traffic": "",
                    "source": "youtube",
                    "category": category_name,
                    "channel": channel,
                }
            )

        return results

    except Exception:
        logger.exception("YouTube Trending 조회 실패")
        return []


def _extract_keyword_from_title(title: str) -> str:
    """YouTube 제목에서 핵심 키워드 추출

    불필요한 부분 제거: [LIVE], MV, Official, 채널명 등
    """
    # 대괄호/괄호 안 메타데이터 제거
    cleaned = re.sub(r"\[.*?\]", "", title)
    cleaned = re.sub(r"\(.*?\)", "", cleaned)

    # 흔한 YouTube 접미어 제거
    remove_patterns = [
        r"\b(Official\s*)?(M/?V|MV|Music\s*Video|Teaser|Trailer|"
        r"Dance\s*Practice|Lyric\s*Video|Performance)\b",
        r"\b(EP\.?\d+|S#\d+)\b",
        r"[|/·].*$",  # 구분자 이후 전부 제거
    ]
    for pat in remove_patterns:
        cleaned = re.sub(pat, "", cleaned, flags=re.IGNORECASE)

    # 앞뒤 공백, 특수문자 정리
    cleaned = re.sub(r"[#@][\w]+", "", cleaned)  # 해시태그 제거
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = cleaned.strip(" -·|'\"")

    # 너무 짧거나 한글이 없으면 스킵
    if len(cleaned) < 2:
        return ""

    return cleaned


async def _filter_keywords_gpt(raw_keywords: list[dict]) -> list[dict]:
    """GPT로 플랫폼 적합 키워드 필터링 (1회 호출로 전체 판별)"""
    keyword_list = [k["keyword"] for k in raw_keywords]

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "gpt-4o-mini",
                    "temperature": 0,
                    "max_tokens": 500,
                    "messages": [
                        {"role": "system", "content": _FILTER_SYSTEM},
                        {
                            "role": "user",
                            "content": _FILTER_USER.format(
                                keywords_json=json.dumps(keyword_list, ensure_ascii=False)
                            ),
                        },
                    ],
                },
            )
            resp.raise_for_status()
            data = resp.json()

        content = data["choices"][0]["message"]["content"].strip()

        # JSON 파싱 (```json ... ``` 래핑 대응)
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        approved: list[str] = json.loads(content)

        # GPT가 다듬은 키워드 + YouTube 검색 URL 생성
        filtered: list[dict] = []
        for kw in approved:
            search_query = quote(kw)
            filtered.append(
                {
                    "keyword": kw,
                    "traffic": "",
                    "source": "curated",
                    "url": f"https://www.youtube.com/results?search_query={search_query}",
                }
            )

        # rank 재부여
        for i, r in enumerate(filtered):
            r["rank"] = i + 1

        logger.info(
            "트렌드 필터링: %d개 → %d개 통과",
            len(raw_keywords),
            len(filtered),
        )
        return filtered

    except Exception:
        logger.exception("GPT 키워드 필터링 실패, 원본 반환")
        return raw_keywords


async def _enrich_with_views(keywords: list[dict]) -> list[dict]:
    """키워드별 YouTube 검색 → 상위 영상 조회수 평균 계산 → 조회수 기준 정렬"""
    api_key = settings.YOUTUBE_API_KEY or settings.GOOGLE_API_KEY
    if not api_key or not keywords:
        return keywords

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            for kw_item in keywords:
                keyword = kw_item["keyword"]
                # 키워드를 단어별로 분리해서 각각 검색
                words = keyword.split()
                total_views = 0
                word_count = 0

                for word in words:
                    if len(word) < 2:
                        continue
                    # YouTube 검색 → 상위 3개 영상 ID
                    search_resp = await client.get(
                        "https://www.googleapis.com/youtube/v3/search",
                        params={
                            "part": "id",
                            "q": word,
                            "type": "video",
                            "regionCode": "KR",
                            "maxResults": 3,
                            "order": "viewCount",
                            "key": api_key,
                        },
                    )
                    if search_resp.status_code != 200:
                        continue

                    video_ids = [
                        item["id"]["videoId"]
                        for item in search_resp.json().get("items", [])
                        if item.get("id", {}).get("videoId")
                    ]
                    if not video_ids:
                        continue

                    # 영상 조회수 조회
                    stats_resp = await client.get(
                        "https://www.googleapis.com/youtube/v3/videos",
                        params={
                            "part": "statistics",
                            "id": ",".join(video_ids),
                            "key": api_key,
                        },
                    )
                    if stats_resp.status_code != 200:
                        continue

                    views = [
                        int(v["statistics"].get("viewCount", 0))
                        for v in stats_resp.json().get("items", [])
                    ]
                    if views:
                        total_views += sum(views) // len(views)
                        word_count += 1

                # 평균 조회수 = 총합 / 단어 수
                avg_views = total_views // word_count if word_count > 0 else 0
                kw_item["avg_views"] = avg_views

        # 조회수 기준 내림차순 정렬
        keywords.sort(key=lambda x: x.get("avg_views", 0), reverse=True)
        for i, kw in enumerate(keywords):
            kw["rank"] = i + 1

    except Exception:
        logger.exception("YouTube 조회수 조회 실패")

    return keywords


def _parse_traffic(t: str) -> int:
    """트래픽 문자열 → 정수 변환"""
    num = t.replace("+", "").replace(",", "").strip()
    try:
        return int(num)
    except ValueError:
        return 0
