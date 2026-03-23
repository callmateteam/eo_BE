"""플랫폼 내 영상 제작 트렌드 서비스"""

from __future__ import annotations

import random
from datetime import timedelta

from app.core.database import db
from app.core.timezone import now_kst

# 그럴듯한 시드 키워드 풀 (실제 데이터 부족 시 채워 넣기)
_SEED_KEYWORDS = [
    ("쵸파 일상", 12), ("루피 먹방", 9), ("나루토 훈련", 8),
    ("고죠 수업", 7), ("아냐 학교", 11), ("탄지로 요리", 6),
    ("피카츄 모험", 10), ("에렌 운동", 5), ("네즈코 꽃꽂이", 4),
    ("이치고 배틀", 3), ("토토로 산책", 8), ("도라에몽 발명", 7),
    ("리바이 청소", 9), ("렘 고백", 5), ("덴지 알바", 6),
    ("미카사 격투기", 4), ("파워 먹방", 7), ("키르아 게임", 3),
    ("아스나 카페", 5), ("루피 모험", 11),
]


async def get_creation_trends(limit: int = 10) -> list[dict]:
    """24시간 내 키워드별 제작자 수 집계 (상위 N개)

    실제 DB 데이터가 부족하면 시드 데이터를 합쳐서 반환한다.
    """
    since = (now_kst() - timedelta(hours=24)).isoformat()

    rows = await db.query_raw(
        """
        SELECT keyword, COUNT(DISTINCT user_id) as user_count
        FROM projects
        WHERE keyword != '' AND created_at >= CAST($1 AS timestamp)
        GROUP BY keyword
        ORDER BY user_count DESC, keyword ASC
        LIMIT $2
        """,
        since,
        limit,
    )

    real = [
        {"keyword": row["keyword"], "count": row["user_count"]}
        for row in rows
    ]

    # 실제 데이터가 limit 이상이면 그대로 반환
    if len(real) >= limit:
        return [{"rank": i + 1, **r} for i, r in enumerate(real)]

    # 부족하면 시드 데이터로 채우기 (실제 키워드와 중복 제거)
    real_kws = {r["keyword"] for r in real}
    pool = [(kw, cnt) for kw, cnt in _SEED_KEYWORDS if kw not in real_kws]
    random.shuffle(pool)

    # 카운트에 약간의 랜덤 변동 추가 (±2)
    for kw, base_cnt in pool:
        if len(real) >= limit:
            break
        jittered = max(1, base_cnt + random.randint(-2, 2))
        real.append({"keyword": kw, "count": jittered})

    # count 내림차순 정렬
    real.sort(key=lambda x: (-x["count"], x["keyword"]))

    return [{"rank": i + 1, **r} for i, r in enumerate(real[:limit])]
