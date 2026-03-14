"""플랫폼 내 영상 제작 트렌드 서비스"""

from __future__ import annotations

from datetime import timedelta

from app.core.database import db
from app.core.timezone import now_kst


async def get_creation_trends(limit: int = 10) -> list[dict]:
    """24시간 내 키워드별 제작자 수 집계 (상위 N개)

    Prisma ORM은 GROUP BY를 직접 지원하지 않으므로 raw query 사용.
    """
    since = now_kst() - timedelta(hours=24)

    rows = await db.query_raw(
        """
        SELECT keyword, COUNT(DISTINCT user_id) as user_count
        FROM projects
        WHERE keyword != '' AND created_at >= $1
        GROUP BY keyword
        ORDER BY user_count DESC, keyword ASC
        LIMIT $2
        """,
        since,
        limit,
    )

    return [
        {
            "rank": idx + 1,
            "keyword": row["keyword"],
            "count": row["user_count"],
        }
        for idx, row in enumerate(rows)
    ]
