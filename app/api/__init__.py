from fastapi import APIRouter

from app.api.auth import router as auth_router
from app.api.character import router as character_router
from app.api.dashboard import router as dashboard_router
from app.api.video import router as video_router

router = APIRouter()
router.include_router(auth_router)
router.include_router(character_router)
router.include_router(dashboard_router)
router.include_router(video_router)


@router.get("/")
async def root():
    return {"message": "EO API"}
