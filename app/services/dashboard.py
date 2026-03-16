from __future__ import annotations

from app.core.database import db
from app.schemas.dashboard import STATUS_LABEL, STATUS_PROGRESS, ProjectStatus, SimpleStatus


async def get_recent_projects(user_id: str, limit: int = 10) -> list[dict]:
    """유저의 최근 프로젝트 목록 조회 (최신순, 캐릭터 포함)"""
    projects = await db.project.find_many(
        where={"userId": user_id},
        order={"createdAt": "desc"},
        take=limit,
        include={"character": True},
    )
    if not projects:
        return None

    result = []
    for p in projects:
        status = p.status
        is_valid = status in ProjectStatus._value2member_map_
        simple = (
            SimpleStatus.COMPLETED
            if status == "COMPLETED"
            else SimpleStatus.IN_PROGRESS
        )

        # 썸네일: 콘티 heroFrameUrl → 없으면 캐릭터 이미지
        thumbnail = p.character.thumbnailUrl if p.character else ""
        storyboard = await db.storyboard.find_first(
            where={"userId": user_id, "characterId": p.characterId},
            order={"createdAt": "desc"},
        )
        if storyboard and storyboard.heroFrameUrl:
            thumbnail = storyboard.heroFrameUrl

        result.append({
            "id": p.id,
            "title": p.title,
            "character_id": p.characterId or "",
            "character_name": p.character.name if p.character else "",
            "character_image": thumbnail,
            "status": status,
            "simple_status": simple,
            "status_label": STATUS_LABEL.get(ProjectStatus(status), "알 수 없음")
            if is_valid
            else "알 수 없음",
            "progress": STATUS_PROGRESS.get(ProjectStatus(status), 0)
            if is_valid
            else 0,
            "created_at": p.createdAt.isoformat(),
        })
    return result


async def get_recent_characters(user_id: str, limit: int = 10) -> list[dict] | None:
    """유저가 사용한 캐릭터 목록 (프리셋+커스텀 통합, 최근 사용순, 중복 제거)"""
    # 1) Project → 프리셋 캐릭터 (최근 것만)
    fetch_limit = limit * 3  # 중복 제거 후 limit개 확보용
    projects = await db.project.find_many(
        where={"userId": user_id},
        order={"createdAt": "desc"},
        take=fetch_limit,
        include={"character": True},
    )
    # 2) Storyboard → 프리셋 + 커스텀 캐릭터
    storyboards = await db.storyboard.find_many(
        where={"userId": user_id},
        order={"createdAt": "desc"},
        take=fetch_limit,
        include={"character": True, "customCharacter": True},
    )

    # (unique_key, iso_time, data) 모아서 최신순 정렬
    entries: list[tuple[str, str, dict]] = []

    for p in projects:
        if not p.character:
            continue
        entries.append(
            (
                f"preset:{p.character.id}",
                p.createdAt.isoformat(),
                _preset_dict(p.character, p.createdAt.isoformat()),
            )
        )

    for sb in storyboards:
        if sb.character:
            entries.append(
                (
                    f"preset:{sb.character.id}",
                    sb.createdAt.isoformat(),
                    _preset_dict(sb.character, sb.createdAt.isoformat()),
                )
            )
        cc = sb.customCharacter
        if cc and cc.status == "COMPLETED":
            entries.append(
                (
                    f"custom:{cc.id}",
                    sb.createdAt.isoformat(),
                    {
                        "id": cc.id,
                        "name": cc.name,
                        "name_en": "",
                        "series": "",
                        "category": cc.style,
                        "image_url": cc.imageUrl1,
                        "thumbnail_url": cc.imageUrl1,
                        "type": "custom",
                        "last_used_at": sb.createdAt.isoformat(),
                    },
                )
            )

    if not entries:
        return None

    # 최신순 정렬 후 중복 제거
    entries.sort(key=lambda x: x[1], reverse=True)
    seen: set[str] = set()
    characters: list[dict] = []
    for key, _, data in entries:
        if key in seen:
            continue
        seen.add(key)
        characters.append(data)
        if len(characters) >= limit:
            break

    return characters if characters else None


def _preset_dict(c: object, last_used_at: str) -> dict:
    """프리셋 캐릭터 → 최근 사용 캐릭터 dict"""
    return {
        "id": c.id,
        "name": c.name,
        "name_en": c.nameEn,
        "series": c.series,
        "category": c.category,
        "image_url": c.imageUrl,
        "thumbnail_url": c.thumbnailUrl,
        "type": "preset",
        "last_used_at": last_used_at,
    }
