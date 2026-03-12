from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.api import router as api_router
from app.core.config import settings
from app.core.database import connect_db, disconnect_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    """앱 시작/종료 시 DB 연결 관리"""
    await connect_db()
    yield
    await disconnect_db()


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="EO Backend API - 쿠키 기반 JWT 인증",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
    swagger_ui_parameters={
        "persistAuthorization": True,
        "withCredentials": True,
    },
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(ValidationError)
async def validation_error_handler(request: Request, exc: ValidationError):
    """Pydantic 유효성 검사 에러를 상세 한글 메시지로 변환"""
    errors = []
    for error in exc.errors():
        field = ".".join(str(loc) for loc in error["loc"]) if error["loc"] else None
        errors.append({"field": field, "message": error["msg"]})

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "detail": "입력값이 올바르지 않습니다.",
            "errors": errors,
        },
    )


app.include_router(api_router, prefix="/api")


@app.get("/health")
async def health_check():
    return {"status": "ok", "version": settings.VERSION}
