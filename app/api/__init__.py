from __future__ import annotations

from fastapi import APIRouter

from app.api.auth import router as auth_router
from app.api.character import router as character_router
from app.api.custom_character import router as custom_char_router
from app.api.dashboard import router as dashboard_router
from app.api.project import router as project_router
from app.api.storyboard import router as storyboard_router
from app.api.video import router as video_router
from app.api.ws import router as ws_router

router = APIRouter()
router.include_router(auth_router)
router.include_router(custom_char_router)
router.include_router(character_router)
router.include_router(dashboard_router)
router.include_router(project_router)
router.include_router(storyboard_router)
router.include_router(video_router)
router.include_router(ws_router)


@router.get("/")
async def root():
    return {"message": "EO API"}
