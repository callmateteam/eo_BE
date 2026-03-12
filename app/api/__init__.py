from fastapi import APIRouter

from app.api.auth import router as auth_router

router = APIRouter()
router.include_router(auth_router)


@router.get("/")
async def root():
    return {"message": "EO API"}
