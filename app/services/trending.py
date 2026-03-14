from __future__ import annotations

import logging

import httpx
from defusedxml import ElementTree

logger = logging.getLogger(__name__)

GOOGLE_TRENDS_RSS = "https://trends.google.co.kr/trending/rss?geo=KR"

# 캐시: 매 요청마다 호출 방지 (인메모리 TTL 캐시)
_trend_cache: dict[str, object] = {"data": None, "expires_at": 0.0}
CACHE_TTL_SECONDS = 600  # 10분


async def fetch_trending_keywords(max_results: int = 10) -> list[dict]:
    """Google Trends 한국 실시간 인기 검색어 (TOP N)"""
    import time

    now = time.time()
    if _trend_cache["data"] and now < _trend_cache["expires_at"]:
        cached = _trend_cache["data"]
        return cached[:max_results]  # type: ignore[index]

    try:
        keywords = await _fetch_google_trends()
        _trend_cache["data"] = keywords
        _trend_cache["expires_at"] = now + CACHE_TTL_SECONDS
        return keywords[:max_results]
    except Exception:
        logger.exception("Google Trends 인기 검색어 조회 실패")
        return []


async def _fetch_google_trends() -> list[dict]:
    """Google Trends RSS 피드에서 한국 인기 검색어 파싱"""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(GOOGLE_TRENDS_RSS)
        resp.raise_for_status()

    root = ElementTree.fromstring(resp.text)
    items = root.findall(".//item")

    ht_ns = "https://trends.google.com/trending/rss"

    results: list[dict] = []
    for idx, item in enumerate(items):
        title = item.findtext("title", "").strip()
        traffic = item.findtext(f"{{{ht_ns}}}approx_traffic", "").strip()

        if not title:
            continue

        results.append(
            {
                "rank": idx + 1,
                "keyword": title,
                "traffic": traffic,
            }
        )

    return results
