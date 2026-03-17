"""프로젝트 서비스 레이어 - DB 로직 + 4단계 트래킹"""

from __future__ import annotations

import logging

from app.core.database import db

logger = logging.getLogger(__name__)

# ── 상수 ──

STAGE_CHARACTER_SELECT = 1
STAGE_IDEA_INPUT = 2
STAGE_STORYBOARD = 3
STAGE_VIDEO_GENERATION = 4

STAGE_NAMES = {
    1: "CHARACTER_SELECT",
    2: "IDEA_INPUT",
    3: "STORYBOARD",
    4: "VIDEO_GENERATION",
}

# 프로젝트 include 옵션 (캐릭터 + 커스텀캐릭터 + 스토리보드 썸네일)
_PROJECT_INCLUDE = {
    "character": True,
    "customCharacter": True,
    "storyboard": {"include": {"scenes": True}},
}


# ── 단계 트래킹 핵심 로직 ──


def _has_character(record: object) -> bool:
    """1단계 데이터(캐릭터) 존재 여부"""
    return bool(record.characterId or getattr(record, "customCharacterId", None))


def _has_idea(record: object) -> bool:
    """2단계 데이터(아이디어) 존재 여부"""
    return bool(getattr(record, "idea", None))


def _has_storyboard(record: object) -> bool:
    """3단계 데이터(스토리보드) 존재 여부"""
    return bool(getattr(record, "storyboardId", None))


def _validate_stage_prerequisites(record: object, target_stage: int) -> None:
    """단계 전환 전 선행 조건 검증.

    Raises:
        ValueError: 선행 단계의 필수 데이터가 없을 때
    """
    if target_stage >= STAGE_IDEA_INPUT and not _has_character(record):
        raise ValueError("1단계(캐릭터 선택)를 먼저 완료해주세요")
    if target_stage >= STAGE_STORYBOARD and not _has_idea(record):
        raise ValueError("2단계(아이디어 입력)를 먼저 완료해주세요")
    if target_stage >= STAGE_VIDEO_GENERATION and not _has_storyboard(record):
        raise ValueError("3단계(스토리보드)를 먼저 완료해주세요")


def _compute_auto_stage(current_stage: int, data: dict, record: object) -> int:
    """PATCH 데이터를 보고 자동 단계 진행을 계산한다.

    규칙:
    - idea가 설정되고 현재 stage < 2 → stage 2로 진행
    - storyboardId가 설정되고 현재 stage < 3 → stage 3로 진행
    - 명시적 currentStage가 있으면 그 값 우선
    - 캐릭터가 변경되면 stage 1로 리셋 (이전 데이터는 유지, 프론트에서 재확인)
    """
    # 명시적 currentStage 지정이 있으면 그것을 우선
    if "currentStage" in data:
        return data["currentStage"]

    new_stage = current_stage

    # 캐릭터 변경 → stage 1로 리셋 (프론트에서 이후 단계 재확인 유도)
    changing_char = "characterId" in data or "customCharacterId" in data
    if changing_char and current_stage > STAGE_CHARACTER_SELECT:
        return STAGE_CHARACTER_SELECT

    # idea 설정 → stage 2로 자동 진행
    if "idea" in data and current_stage < STAGE_IDEA_INPUT:
        new_stage = STAGE_IDEA_INPUT

    # storyboardId 설정 → stage 3로 자동 진행
    if "storyboardId" in data and new_stage < STAGE_STORYBOARD:
        new_stage = STAGE_STORYBOARD

    return new_stage


# ── CRUD ──


async def create_project(
    title: str,
    keyword: str,
    user_id: str,
    character_id: str | None = None,
    custom_character_id: str | None = None,
) -> dict:
    """새 프로젝트를 생성한다 (1단계 완료 상태).

    경로 A: character_id 전달 (프리셋 캐릭터)
    경로 B: custom_character_id 전달 (커스텀 캐릭터)

    Raises:
        ValueError: 캐릭터가 존재하지 않거나 둘 다 없을 때
    """
    if not character_id and not custom_character_id:
        raise ValueError("character_id 또는 custom_character_id 중 하나는 필수입니다")

    data: dict = {
        "title": title,
        "keyword": keyword,
        "userId": user_id,
        "currentStage": STAGE_CHARACTER_SELECT,
    }

    if character_id:
        char = await db.character.find_unique(where={"id": character_id})
        if not char:
            raise ValueError("캐릭터를 찾을 수 없습니다")
        data["characterId"] = character_id
    else:
        custom = await db.customcharacter.find_unique(where={"id": custom_character_id})
        if not custom:
            raise ValueError("커스텀 캐릭터를 찾을 수 없습니다")
        data["customCharacterId"] = custom_character_id

    record = await db.project.create(data=data)
    return {
        "id": record.id,
        "title": record.title,
        "current_stage": record.currentStage,
    }


async def update_project(
    project_id: str,
    user_id: str,
    **fields: object,
) -> object | None:
    """프로젝트를 수정한다 (본인 소유만).

    단계 트래킹 로직:
    - idea 설정 시 자동으로 stage 2 진행
    - storyboard_id 설정 시 자동으로 stage 3 진행
    - 캐릭터 변경 시 stage 1로 리셋
    - 명시적 current_stage 지정 가능 (이전 단계로 돌아가기)
    - 각 단계 전환 시 선행 조건 검증

    Raises:
        ValueError: 참조하는 캐릭터/스토리보드가 존재하지 않거나 단계 조건 미충족 시
    """
    record = await db.project.find_first(
        where={"id": project_id, "userId": user_id},
    )
    if not record:
        return None

    # snake_case → camelCase 매핑
    field_map = {
        "title": "title",
        "keyword": "keyword",
        "character_id": "characterId",
        "custom_character_id": "customCharacterId",
        "storyboard_id": "storyboardId",
        "idea": "idea",
        "current_stage": "currentStage",
    }

    data: dict = {}
    for key, value in fields.items():
        if value is not None and key in field_map:
            data[field_map[key]] = value

    # 외래키 검증
    if "characterId" in data:
        char = await db.character.find_unique(where={"id": data["characterId"]})
        if not char:
            raise ValueError("캐릭터를 찾을 수 없습니다")

    if "customCharacterId" in data:
        custom = await db.customcharacter.find_unique(where={"id": data["customCharacterId"]})
        if not custom:
            raise ValueError("커스텀 캐릭터를 찾을 수 없습니다")

    if "storyboardId" in data:
        sb = await db.storyboard.find_first(
            where={"id": data["storyboardId"], "userId": user_id},
        )
        if not sb:
            raise ValueError("스토리보드를 찾을 수 없습니다")

    if not data:
        return await db.project.find_first(
            where={"id": project_id},
            include=_PROJECT_INCLUDE,
        )

    # ── 단계 트래킹 ──
    # 업데이트 후의 가상 레코드로 선행 조건 검증
    merged = _merge_record(record, data)
    auto_stage = _compute_auto_stage(record.currentStage, data, merged)
    _validate_stage_prerequisites(merged, auto_stage)
    data["currentStage"] = auto_stage

    updated = await db.project.update(
        where={"id": project_id},
        data=data,
        include=_PROJECT_INCLUDE,
    )

    logger.info(
        "프로젝트 단계 변경: %s stage %d→%d (%s)",
        project_id,
        record.currentStage,
        auto_stage,
        STAGE_NAMES.get(auto_stage, "?"),
    )

    return updated


async def link_storyboard(project_id: str, storyboard_id: str) -> None:
    """프로젝트에 스토리보드를 연결하고 3단계로 진행한다.

    콘티 생성 완료(READY) 시 자동 호출된다.
    """
    record = await db.project.find_first(where={"id": project_id})
    if not record:
        logger.warning("link_storyboard: 프로젝트 없음 %s", project_id)
        return

    # 이미 같은 스토리보드가 연결되어 있으면 무시
    if record.storyboardId == storyboard_id:
        return

    await db.project.update(
        where={"id": project_id},
        data={
            "storyboardId": storyboard_id,
            "currentStage": STAGE_STORYBOARD,
        },
    )
    logger.info(
        "프로젝트-스토리보드 연결: project=%s storyboard=%s → stage 3",
        project_id,
        storyboard_id,
    )


async def advance_to_video_generating(project_id: str) -> None:
    """영상 생성 시작 시 프로젝트 상태를 업데이트한다."""
    record = await db.project.find_first(where={"id": project_id})
    if not record:
        return

    await db.project.update(
        where={"id": project_id},
        data={"status": "VIDEO_GENERATED"},
    )
    logger.info("프로젝트 영상 생성 시작 상태 업데이트: %s", project_id)


async def advance_to_video_complete(project_id: str) -> None:
    """영상 생성 완료 시 프로젝트를 4단계로 진행한다.

    video_generation 서비스에서 호출된다.
    """
    record = await db.project.find_first(where={"id": project_id})
    if not record:
        return

    if record.currentStage >= STAGE_VIDEO_GENERATION:
        return

    await db.project.update(
        where={"id": project_id},
        data={
            "currentStage": STAGE_VIDEO_GENERATION,
            "status": "COMPLETED",
        },
    )
    logger.info("프로젝트 4단계(영상완료) 자동 진행: %s", project_id)


async def list_projects(user_id: str) -> list[object]:
    """사용자의 프로젝트 목록을 최신순으로 조회한다 (최대 100건)."""
    return await db.project.find_many(
        where={"userId": user_id},
        order={"createdAt": "desc"},
        take=100,
        include=_PROJECT_INCLUDE,
    )


async def get_project(project_id: str, user_id: str) -> object | None:
    """프로젝트 상세를 조회한다 (본인 소유만)."""
    return await db.project.find_first(
        where={"id": project_id, "userId": user_id},
        include=_PROJECT_INCLUDE,
    )


async def delete_project(project_id: str, user_id: str) -> bool:
    """프로젝트를 삭제한다 (연관 스토리보드 cascade)."""
    record = await db.project.find_first(
        where={"id": project_id, "userId": user_id},
    )
    if not record:
        return False

    if record.storyboardId:
        await db.storyboard.delete(where={"id": record.storyboardId})

    await db.project.delete(where={"id": project_id})
    return True


# ── 내부 유틸 ──


class _Merged:
    """업데이트 후의 가상 레코드 (검증용)"""

    def __init__(self, record: object, data: dict) -> None:
        self._record = record
        self._data = data

    def __getattr__(self, name: str):
        if name.startswith("_"):
            return super().__getattribute__(name)
        if name in self._data:
            return self._data[name]
        return getattr(self._record, name)


def _merge_record(record: object, data: dict) -> _Merged:
    return _Merged(record, data)
