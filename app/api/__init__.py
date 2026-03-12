from fastapi import APIRouter

from app.api.auth import router as auth_router
from app.api.dashboard import router as dashboard_router

router = APIRouter()
router.include_router(auth_router)
router.include_router(dashboard_router)


@router.get("/")
async def root():
    return {"message": "EO API"}
