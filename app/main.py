from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.api import router as api_router
from app.core.config import settings
from app.core.database import connect_db, disconnect_db
from app.core.trend_manager import trend_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    """앱 시작/종료 시 DB 연결 관리"""
    await connect_db()
    trend_manager.start()
    yield
    trend_manager.stop()
    await disconnect_db()


SWAGGER_DESCRIPTION = """
## EO Backend API

AI 기반 숏폼 영상 생성 플랫폼 백엔드 API

### 주요 기능
- **캐릭터**: 프리셋 캐릭터 선택 또는 커스텀 캐릭터 생성 (GPT-4o Vision 분석)
- **콘티(스토리보드)**: GPT-4o-mini 장면 분할 + GPT 이미지 생성 (Veo 시작 프레임 겸용)
- **영상 생성**: Veo 기반 숏폼 영상 생성 (최대 60초)
- **대시보드**: 최근 프로젝트, 사용 캐릭터, 실시간 트렌드 통합 조회

### 인증 방식
- **쿠키 기반 JWT**: 로그인 시 `access_token`(30분) + `refresh_token`(7일) 쿠키 자동 설정
- **구글 OAuth**: Google id_token 검증 후 동일한 쿠키 발급
- **WebSocket 인증**: 쿠키의 JWT로 인증 (트렌드 WS 제외)

### 에러 응답 형식
```json
{
  "detail": "에러 요약 메시지",
  "errors": [
    {"field": "필드명 또는 null", "message": "상세 에러 메시지"}
  ]
}
```

### 공통 에러 코드
| 코드 | 설명 |
|------|------|
| 400 | 유효성 검사 실패 (잘못된 입력) |
| 401 | 인증 필요 (쿠키 없음/만료/무효) |
| 404 | 리소스를 찾을 수 없음 |
| 409 | 충돌 (중복 아이디, 이미지 생성 중 재요청 등) |
| 422 | 요청 파라미터 형식 오류 |
| 429 | 동시 생성 제한 초과 (콘티 최대 3개) |
| 500 | 서버 내부 오류 |

### WebSocket 엔드포인트

#### `ws://{host}/api/ws/trends` — 실시간 트렌드 (인증 불필요)
- 연결 즉시 현재 데이터 전송, 이후 30초 간격 자동 업데이트
- **youtube**: Google Trends 한국 인기 검색어 (10분 캐시)
- **creation**: 플랫폼 내 24시간 영상 제작 키워드 순위
```json
{"youtube": [{"rank": 1, "keyword": "키워드", "traffic": "500K+"}],
 "creation": [{"rank": 1, "keyword": "키워드", "count": 12}]}
```

#### `ws://{host}/api/characters/custom/ws/{character_id}` — 커스텀 캐릭터 진행률 (쿠키 인증)
- PROCESSING → COMPLETED / FAILED, 완료/실패 시 자동 종료
```json
{"character_id": "uuid", "progress": 40, "step": "AI 캐릭터 분석 중...", "status": "PROCESSING"}
```

#### `ws://{host}/api/storyboards/ws/{storyboard_id}` — 콘티 생성 진행률 (쿠키 인증)
- GENERATING → READY / FAILED, 완료/실패 시 자동 종료
```json
{"id": "uuid", "progress": 40, "step": "장면 3개 시작 프레임 생성 중...", "status": "GENERATING"}
```

#### 장면 이미지 재생성 진행률 (쿠키 인증)
`ws://{host}/api/storyboards/ws/scenes/{scene_id}/image`
- content 기반 새 프롬프트 생성 → GPT 이미지 재생성
```json
{"id": "uuid", "progress": 45,
 "step": "시작 프레임 생성 중...", "status": "GENERATING"}
```

### 콘티 장면 이미지 상태 (imageStatus)
| 상태 | 설명 |
|------|------|
| PENDING | 이미지 생성 대기 |
| GENERATING | 이미지 생성 중 |
| COMPLETED | 이미지 생성 완료 |
| STALE | 장면 내용 수정됨 (이미지 갱신 필요) |
| FAILED | 이미지 생성 실패 |
"""

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description=SWAGGER_DESCRIPTION,
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
