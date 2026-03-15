"""프로젝트 서비스 레이어 - DB 로직 담당"""

from __future__ import annotations

from app.core.database import db


async def create_project(
    title: str,
    keyword: str,
    character_id: str,
    user_id: str,
) -> dict:
    """새 프로젝트를 생성한다.

    캐릭터 존재를 확인한 뒤 프로젝트 레코드를 만들어 dict로 반환한다.

    Raises:
        ValueError: 캐릭터가 존재하지 않을 때
    """
    char = await db.character.find_unique(where={"id": character_id})
    if not char:
        raise ValueError("캐릭터를 찾을 수 없습니다")

    record = await db.project.create(
        data={
            "title": title,
            "keyword": keyword,
            "characterId": character_id,
            "userId": user_id,
        }
    )
    return {"id": record.id, "title": record.title}


async def list_projects(user_id: str) -> list[dict]:
    """사용자의 프로젝트 목록을 최신순으로 조회한다 (최대 100건).

    캐릭터 정보를 포함하여 반환한다.
    """
    records = await db.project.find_many(
        where={"userId": user_id},
        order={"createdAt": "desc"},
        take=100,
        include={"character": True},
    )
    return records


async def get_project(project_id: str, user_id: str) -> object | None:
    """프로젝트 상세를 조회한다 (본인 소유만).

    캐릭터 정보를 포함하여 반환하며, 없으면 None을 반환한다.
    """
    record = await db.project.find_first(
        where={"id": project_id, "userId": user_id},
        include={"character": True},
    )
    return record


async def delete_project(project_id: str, user_id: str) -> bool:
    """프로젝트를 삭제한다 (본인 소유 확인).

    소유권 확인 후 삭제하며, 프로젝트가 없으면 False를 반환한다.
    """
    record = await db.project.find_first(
        where={"id": project_id, "userId": user_id},
    )
    if not record:
        return False

    await db.project.delete(where={"id": project_id})
    return True
