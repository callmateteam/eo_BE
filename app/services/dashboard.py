from __future__ import annotations

from app.core.database import db
from app.schemas.dashboard import STATUS_LABEL, STATUS_PROGRESS, ProjectStatus


async def get_recent_projects(user_id: str, limit: int = 10) -> list[dict]:
    """유저의 최근 프로젝트 목록 조회 (최신순, 캐릭터 포함)"""
    projects = await db.project.find_many(
        where={"userId": user_id},
        order={"createdAt": "desc"},
        take=limit,
        include={"character": True},
    )
    return [
        {
            "id": p.id,
            "title": p.title,
            "character_id": p.characterId,
            "character_name": p.character.name if p.character else "",
            "character_image": p.character.thumbnailUrl if p.character else "",
            "status": p.status,
            "status_label": STATUS_LABEL.get(ProjectStatus(p.status), "알 수 없음"),
            "progress": STATUS_PROGRESS.get(ProjectStatus(p.status), 0),
            "created_at": p.createdAt.isoformat(),
        }
        for p in projects
    ]


async def get_recent_characters(user_id: str, limit: int = 10) -> list[dict] | None:
    """유저가 사용한 캐릭터 목록 (최근 사용순, 중복 제거)"""
    projects = await db.project.find_many(
        where={"userId": user_id},
        order={"createdAt": "desc"},
        include={"character": True},
    )

    if not projects:
        return None

    seen: set[str] = set()
    characters: list[dict] = []

    for p in projects:
        if not p.character or p.character.id in seen:
            continue
        seen.add(p.character.id)
        characters.append(
            {
                "id": p.character.id,
                "name": p.character.name,
                "name_en": p.character.nameEn,
                "series": p.character.series,
                "category": p.character.category,
                "image_url": p.character.imageUrl,
                "thumbnail_url": p.character.thumbnailUrl,
                "last_used_at": p.createdAt.isoformat(),
            }
        )
        if len(characters) >= limit:
            break

    return characters if characters else None
