from __future__ import annotations

from app.core.database import db


async def get_recent_projects(user_id: str, limit: int = 10) -> list[dict]:
    """유저의 최근 프로젝트 목록 조회 (최신순)"""
    projects = await db.project.find_many(
        where={"userId": user_id},
        order={"createdAt": "desc"},
        take=limit,
    )
    return [
        {
            "id": p.id,
            "title": p.title,
            "character_name": p.characterName,
            "character_image": p.characterImage,
            "created_at": p.createdAt.isoformat(),
        }
        for p in projects
    ]
