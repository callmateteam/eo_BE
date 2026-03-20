from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.api import router as api_router
from app.core.config import settings
from app.core.database import connect_db, disconnect_db
from app.core.http_client import close_clients
from app.core.trend_manager import trend_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    """앱 시작/종료 시 DB 연결 관리"""
    await connect_db()
    trend_manager.start()
    yield
    trend_manager.stop()
    await close_clients()
    await disconnect_db()


SWAGGER_DESCRIPTION = """
## EO Backend API

AI 기반 숏폼 영상 생성 플랫폼 백엔드 API

### 주요 기능
- **프로젝트**: 5단계 파이프라인 (캐릭터 선택 → 아이디어 입력 → 아이디어 구체화 → 콘티 생성 → 영상 생성), 단계별 임시저장/재개
- **캐릭터**: 프리셋 캐릭터(4개 카테고리) 선택 또는 커스텀 캐릭터 생성 (이미지 2장 + GPT-4o Vision 분석)
- **콘티(스토리보드)**: GPT-4o-mini 장면 분할 (3~5장) + gpt-image-1 시작 프레임 생성, 씬별 수정/이미지 재생성
- **영상 생성**: Hailuo(fal.ai) / Pika(fal.ai) 기반 image-to-video, 씬별 병렬 생성 → ffmpeg 자동 병합 (최대 60초)
- **대시보드**: 최근 프로젝트 10개, 최근 사용 캐릭터, YouTube/Google Trends + 플랫폼 내 제작 트렌드

### 프로젝트 생성 경로
| 경로 | 설명 | 시작 단계 |
|------|------|----------|
| **A. 기존 캐릭터 선택** | 프리셋 또는 기존 커스텀 캐릭터 선택 후 영상 제작 | 2단계 (아이디어 입력) |
| **B. 새 캐릭터 생성** | 커스텀 캐릭터 생성(WS 진행률) → 등록 후 영상 제작 | 1단계 (캐릭터 생성) |

### 프로젝트 5단계 트래킹 (`currentStage`)
| 단계 | stage_name | 설명 | 저장 데이터 |
|------|------------|------|------------|
| 1 | CHARACTER_SELECT | 캐릭터 생성 또는 선택 | character_id 또는 custom_character_id |
| 2 | IDEA_INPUT | 아이디어 텍스트 입력 | idea (최대 2000자) |
| 3 | IDEA_ENRICHMENT | GPT 아이디어 구체화 (배경/분위기/캐릭터/스토리) → 사용자 수정 후 확정 | enrichedIdea (JSON) |
| 4 | STORYBOARD | 콘티 생성 및 씬별 수정 (enrichedIdea 기반) | storyboard_id (씬 데이터 포함) |
| 5 | VIDEO_GENERATION | 씬별 영상 생성 및 편집 | 각 씬 videoUrl + finalVideoUrl |

- 수정 시 `currentStage` 기준으로 해당 단계 화면부터 재개
- `PATCH /api/projects/{id}`로 단계별 데이터 저장 시 자동으로 `currentStage` 진행
- `GET /api/projects/{id}` 응답에 `stages` 배열로 전체 단계별 상태/데이터 포함

### 인증 방식
- **쿠키 기반 JWT (HS256)**: 로그인 시 `access_token`(30분, httpOnly) + `refresh_token`(7일, httpOnly, path=/api/auth) 쿠키 자동 설정
- **구글 OAuth**: Google id_token 검증 후 동일한 쿠키 발급, 신규 유저 자동 가입
- **토큰 로테이션**: refresh 시 기존 토큰 폐기 + 새 토큰 발급
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
| 400 | 유효성 검사 실패 / 캐릭터 선택 오류 / 단계 조건 미충족 |
| 401 | 인증 필요 (쿠키 없음/만료/무효) |
| 404 | 리소스를 찾을 수 없음 |
| 409 | 충돌 (중복 아이디, 이미지 생성 중 재요청, 사용 중 캐릭터 삭제 등) |
| 422 | 요청 파라미터 형식 오류 (Pydantic 검증 실패) |
| 429 | 동시 생성 제한 초과 (콘티 유저당 최대 3개) |
| 500 | 서버 내부 오류 (영상 생성 API 호출 실패 등) |

---

### REST API 엔드포인트

#### Auth (`/api/auth`) — tag: `auth`
| Method | Path | Summary | 인증 | 상태코드 |
|--------|------|---------|------|---------|
| POST | `/validate-username` | 아이디 유효성 검사 + verification_token 발급 (5분 유효) | X | 200, 400, 409, 422 |
| POST | `/signup` | 회원가입 (name + username + password + verification_token) | X | 201, 400, 409, 422 |
| POST | `/login` | 로그인 → access_token + refresh_token 쿠키 설정 | X | 200, 401 |
| POST | `/google` | Google OAuth 로그인 (id_token → 쿠키 발급, 신규 시 자동가입) | X | 200, 401 |
| POST | `/google/link` | 기존 계정에 Google 연동 | O | 200, 401, 409 |
| POST | `/refresh` | access_token 갱신 (refresh_token 쿠키 사용, 토큰 로테이션) | X | 200, 401 |
| POST | `/logout` | 로그아웃 (쿠키 삭제 + refresh_token 폐기) | O | 200, 401 |
| GET | `/me` | 내 정보 조회 (프로필 + 소셜 연동 상태) | O | 200, 401 |

#### Characters (`/api/characters`) — tag: `characters`
| Method | Path | Summary | 인증 | 상태코드 |
|--------|------|---------|------|---------|
| GET | `` | 전체 프리셋 캐릭터 목록 (sortOrder 정렬, isActive=true) | X | 200 |
| GET | `/category/{category}` | 카테고리별 캐릭터 목록 | X | 200, 422 |
| GET | `/{character_id}` | 캐릭터 단건 조회 | X | 200, 404 |

- **category enum**: `MEME`(밈/표정), `ACTION`(액션), `CUTE`(귀여운), `BEAUTY`(인기 미남/미소녀)

#### Custom Characters (`/api/characters/custom`) — tag: `custom-characters`
| Method | Path | Summary | 인증 | 상태코드 |
|--------|------|---------|------|---------|
| POST | `` | 커스텀 캐릭터 생성 (multipart: image1, image2, name, description, style, voice_id) | O | 201, 400, 401, 422 |
| GET | `` | 내 커스텀 캐릭터 목록 | O | 200, 401 |
| GET | `/{character_id}` | 커스텀 캐릭터 단건 조회 (본인 소유만) | O | 200, 401, 404 |
| DELETE | `/{character_id}` | 커스텀 캐릭터 삭제 (스토리보드 참조 시 409) | O | 204, 401, 404, 409 |

- **이미지**: PNG/JPG/WebP, 각 최대 10MB
- **style enum**: `REALISTIC`(실사) · `ANIME`(애니메이션) · `CARTOON_3D`(3D 카툰) · `ILLUSTRATION_2D`(2D 일러스트) · `CLAY`(클레이) · `WATERCOLOR`(수채화)
- **voice_id enum**: `alloy` · `ash` · `ballad` · `coral` · `echo` · `fable` · `onyx` · `nova` · `sage` · `shimmer` (기본값: alloy)
- 생성 후 백그라운드에서 S3 업로드 → GPT-4o Vision 분석 → veoPrompt/voiceStyle 자동 생성

#### Projects (`/api/projects`) — tag: `projects`
| Method | Path | Summary | 인증 | 상태코드 |
|--------|------|---------|------|---------|
| POST | `` | 프로젝트 생성 (title + keyword + character_id 또는 custom_character_id) | O | 201, 400, 401 |
| GET | `` | 내 프로젝트 목록 (썸네일, 캐릭터명, currentStage, progress 포함) | O | 200, 401 |
| GET | `/{project_id}` | 프로젝트 상세 (본인 소유만, 5단계 stages 배열 + 전체 데이터 포함) | O | 200, 401, 404 |
| PATCH | `/{project_id}` | 프로젝트 수정 (title, keyword, idea, enriched_idea, character_id, custom_character_id, storyboard_id, current_stage) | O | 200, 400, 401, 404 |
| POST | `/{project_id}/enrich-idea` | 아이디어 구체화 — GPT가 배경/분위기/메인캐릭터/보조캐릭터/스토리로 구조화 (미리보기) | O | 200, 400, 401, 404 |
| POST | `/{project_id}/confirm-enriched-idea` | 구체화 아이디어 확정 — 사용자 수정 반영 후 3단계 완료 → stage 3 진행 | O | 200, 400, 401, 404 |
| DELETE | `/{project_id}` | 프로젝트 삭제 (본인 소유만) | O | 204, 401, 404 |

- **목록 응답 필드**: id, title, current_stage, stage_name, character_name, character_image, thumbnail_url, status, status_label, progress(%), created_at, updated_at
- **상세 응답**: 위 필드 + idea, enriched_idea(JSON), storyboard_id, **stages**(5단계 배열: stage, name, label, completed, data)
- **썸네일**: 연결된 스토리보드의 heroFrameUrl 또는 첫 번째 씬 imageUrl
- **아이디어 구체화 플로우**: `enrich-idea`(GPT 미리보기) → 프론트에서 편집 → `confirm-enriched-idea`(확정) → 콘티 생성 시 enrichedIdea 자동 반영

#### Storyboards (`/api/storyboards`) — tag: `storyboards`
| Method | Path | Summary | 인증 | 상태코드 |
|--------|------|---------|------|---------|
| POST | `` | 콘티 생성 (idea 10~2000자 + character_id 또는 custom_character_id + project_id) | O | 201, 400, 401, 422, 429 |
| GET | `` | 내 콘티 목록 (idea 100자 요약, scene_count, total_duration) | O | 200, 401 |
| GET | `/{storyboard_id}` | 콘티 상세 (씬 목록 + project_id + final_video_url 포함) | O | 200, 401, 404 |
| PATCH | `/{storyboard_id}/scenes/{scene_id}` | 장면 수정 (title/content, content 변경 시 imageStatus→STALE) | O | 200, 400, 401, 404 |
| POST | `/{storyboard_id}/scenes/{scene_id}/regenerate-image` | 장면 이미지 재생성 (gpt-image-1, 이미 생성 중이면 409) | O | 200, 401, 404, 409 |
| POST | `/{storyboard_id}/generate-videos` | 전체 씬 영상 생성 시작 (READY + 모든 이미지 COMPLETED 필요) | O | 202, 400, 401, 404, 409 |

- **씬 응답 필드**: id, scene_order, title, content, image_prompt, image_url, image_status, has_character, duration, narration, narration_style, narration_url, video_url, video_status, video_error
- **콘티 생성**: 유저당 동시 최대 3개 (초과 시 429), 이미지 병렬 생성 최대 3개, 30초 타임아웃/이미지
- **영상 생성**: 씬별 병렬 최대 3개, 성공한 씬 자동 합본, 개별 실패 시 나머지 계속 진행

#### Video (`/api/video`) — tag: `video`
| Method | Path | Summary | 인증 | 상태코드 |
|--------|------|---------|------|---------|
| POST | `/generate` | 단일 영상 생성 (character_id + prompt + mode + duration + aspect_ratio) | O | 200, 401, 404, 422, 500 |
| GET | `/status/{task_id}` | 영상 생성 상태 조회 (IN_PROGRESS → SUCCESS / FAILED) | O | 200, 400, 401, 500 |

- **mode enum**: `std`(표준) · `pro`(고품질, 기본값)
- **aspect_ratio enum**: `9:16`(세로, 기본값) · `16:9`(가로) · `1:1`(정사각)
- **duration**: 5~10초

#### Video Edit (`/api/storyboards/{id}/...`) — tag: `video-edit`
| Method | Path | Summary | 인증 | 상태코드 |
|--------|------|---------|------|---------|
| GET | `/{id}/edit` | 편집 상태 조회 (없으면 자동 초기화) | O | 200, 401, 404 |
| PATCH | `/{id}/edit` | 편집 저장 (version++ + 히스토리 자동 생성) | O | 200, 401, 404 |
| POST | `/{id}/edit/undo` | 되돌리기 (최대 50단계) | O | 200, 401, 409 |
| POST | `/{id}/edit/tts` | 커스텀 TTS 생성 (텍스트 → audio_url) | O | 200, 401, 500 |
| POST | `/{id}/thumbnail` | 썸네일 프레임 추출 (시간 지정) | O | 200, 401, 404, 500 |
| POST | `/{id}/render` | 최종 렌더링 시작 (편집 적용, WS 진행률) | O | 202, 401, 404 |
| POST | `/{id}/finalize` | 영상 완성 (제목 입력 → 프로젝트 COMPLETED) | O | 200, 401, 404 |
| GET | `/{id}/video-info` | 완성 영상 정보 (제목, 시간, URL, 썸네일) | O | 200, 401, 404 |
| GET | `/{id}/download` | 영상 mp4 다운로드 (스트리밍) | O | 200, 401, 404 |

- **편집 기능**: 씬 순서 변경, 트림(0.001초 정밀도), 배속(0.5~2.0x), 전환 효과(5종), 구간 음소거/볼륨, BGM, 자막(폰트8종/색상/배경/그림자/위치/애니메이션3종), 커스텀 TTS 오버레이, 썸네일
- **완성 플로우**: render(인코딩,WS%) → finalize(제목입력) → video-info(시간확인) → download(다운로드)
- **되돌리기**: PATCH마다 히스토리 자동 저장, POST undo로 복원
- **자막 폰트**: NanumGothic, NanumMyeongjo, NanumSquareRound, NanumBarunGothic, MapoFlowerIsland, GmarketSans, Pretendard, DoHyeon
- **전환 효과**: none, fade, dissolve, slide_left, slide_up, wipe
- **자막 애니메이션**: none, typing, popup, fadein

#### Dashboard (`/api/dashboard`) — tag: `dashboard`
| Method | Path | Summary | 인증 | 상태코드 |
|--------|------|---------|------|---------|
| GET | `` | 대시보드 조회 | O | 200, 401 |

- **응답**: recent_projects(최근 10개, null 가능), recent_characters(프리셋+커스텀 통합, 중복 제거, null 가능), trending_keywords(YouTube/Google Trends 상위 5개), creation_trends(플랫폼 내 24시간 제작 키워드 순위, null 가능)

---

### WebSocket 엔드포인트

> 모든 인증 필요 WS는 쿠키의 JWT로 인증합니다.
> 에러 시 close code: **4001**(인증 실패), **4004**(리소스 없음).
> 터미널 상태(완료/실패) 도달 시 서버가 자동으로 연결을 종료합니다.

#### `ws://{host}/api/ws/trends` — 실시간 트렌드 (인증 불필요)
- 연결 즉시 현재 데이터 전송, 이후 TrendManager가 30초 간격 자동 push
- **youtube**: rank, keyword, avg_views, url (YouTube 검색 링크)
- **creation**: rank, keyword, count (24시간 내 유저별 고유 제작 수)
```json
{"youtube": [{"rank": 1, "keyword": "키워드", "avg_views": 50000, "url": "..."}],
 "creation": [{"rank": 1, "keyword": "키워드", "count": 12}]}
```

#### `ws://{host}/api/characters/custom/ws/{character_id}` — 커스텀 캐릭터 생성 진행률 (쿠키 인증)
- 연결 즉시 현재 상태 전송, PROCESSING이 아니면 바로 종료
- 진행: S3 업로드(10~30%) → GPT-4o Vision 분석(40~70%) → 저장(100%)
- 상태: PROCESSING → COMPLETED / FAILED
```json
{"character_id": "uuid", "progress": 40, "step": "AI 캐릭터 분석 중...", "status": "PROCESSING"}
```

#### `ws://{host}/api/storyboards/ws/{storyboard_id}` — 콘티 생성 진행률 (쿠키 인증)
- 연결 즉시 현재 상태 전송, GENERATING이 아니면 바로 종료
- 진행: GPT 장면 분할 → 이미지 프롬프트 변환 → gpt-image-1 병렬 생성 (최대 3개 동시)
- 상태: GENERATING → READY(=COMPLETED) / FAILED
```json
{"id": "uuid", "progress": 60, "step": "장면 3개 시작 프레임 생성 중...", "status": "PROCESSING"}
```

#### `ws://{host}/api/storyboards/ws/{storyboard_id}/video` — 영상 생성 진행률 (쿠키 인증)
- 연결 즉시 현재 상태 전송, VIDEO_GENERATING이 아니면 바로 종료
- 씬별 병렬 영상 생성 (Hailuo 8초 폴링/360초 타임아웃, Pika 10초/300초)
- 상태: VIDEO_GENERATING → VIDEO_READY / FAILED
```json
{"storyboard_id": "uuid", "status": "VIDEO_GENERATING",
 "overall_progress": 50, "estimated_remaining_seconds": 120,
 "scenes": [{"id": "uuid", "scene_order": 1, "video_status": "COMPLETED", "video_url": "...", "error": null}],
 "final_video_url": null}
```

#### `ws://{host}/api/storyboards/ws/scenes/{scene_id}/image` — 장면 이미지 재생성 진행률 (쿠키 인증)
- 연결 즉시 현재 상태 전송, GENERATING이 아니면 바로 종료
- content → GPT-4o-mini 영문 프롬프트 변환 → gpt-image-1 이미지 재생성 (30초 타임아웃)
- 상태: GENERATING → COMPLETED / FAILED
```json
{"id": "uuid", "progress": 45, "step": "시작 프레임 생성 중...", "status": "GENERATING"}
```

#### `ws://{host}/api/storyboards/ws/{storyboard_id}/render` — 렌더링 진행률 (쿠키 인증)
- 편집 적용 최종 렌더링 진행률 (트림→전환→오디오→TTS→BGM→자막→업로드)
- RENDERING → RENDER_READY / FAILED, 완료 시 자동 종료
```json
{"storyboard_id": "uuid", "status": "RENDERING", "progress": 65, "step": "자막 입히는 중..."}
```

---

### 상태 Enum 참조

#### 프로젝트 상태 (ProjectStatus)
| 상태 | 한글 | progress |
|------|------|---------|
| CREATED | 프로젝트 생성 | 0% |
| SCRIPT_WRITTEN | 스크립트 작성 완료 | 25% |
| VOICE_GENERATED | 음성 생성 완료 | 50% |
| VIDEO_GENERATED | 영상 생성 완료 | 75% |
| COMPLETED | 완료 | 100% |

#### 스토리보드 상태 (Storyboard.status)
| 상태 | 설명 |
|------|------|
| GENERATING | 콘티 생성 중 (GPT 장면 분할 + 이미지 생성) |
| READY | 콘티 생성 완료 (영상 생성 가능) |
| VIDEO_GENERATING | 씬별 영상 생성 중 |
| VIDEO_READY | 영상 생성 완료 (finalVideoUrl 설정됨) |
| FAILED | 생성 실패 (errorMsg 참조) |

#### 씬 이미지 상태 (StoryboardScene.imageStatus)
| 상태 | 설명 |
|------|------|
| PENDING | 이미지 생성 대기 |
| GENERATING | 이미지 생성 중 |
| COMPLETED | 이미지 생성 완료 |
| STALE | 장면 content 수정됨 → 이미지 재생성 필요 |
| FAILED | 이미지 생성 실패 |

#### 씬 영상 상태 (StoryboardScene.videoStatus)
| 상태 | 설명 |
|------|------|
| PENDING | 영상 생성 대기 |
| GENERATING | 영상 생성 중 (videoStartedAt 기록) |
| COMPLETED | 영상 생성 완료 (videoUrl 설정됨) |
| FAILED | 영상 생성 실패 (videoError 참조) |

#### 커스텀 캐릭터 상태 (CustomCharacter.status)
| 상태 | 설명 |
|------|------|
| PROCESSING | S3 업로드 + GPT 분석 진행 중 |
| COMPLETED | 캐릭터 생성 완료 (veoPrompt, voiceStyle 설정됨) |
| FAILED | 생성 실패 (errorMsg 참조) |

#### 커스텀 캐릭터 스타일 (CharacterStyle)
| 값 | 한글 | 프롬프트 |
|----|------|---------|
| REALISTIC | 실사 | photorealistic live action style |
| ANIME | 애니메이션 | anime-inspired live action style |
| CARTOON_3D | 3D 카툰 | 3D cartoon Pixar-style CGI |
| ILLUSTRATION_2D | 2D 일러스트 | 2D flat illustration style |
| CLAY | 클레이 | claymation stop-motion style |
| WATERCOLOR | 수채화 | watercolor painting style |

#### TTS 음성 (VoiceId)
`alloy` · `ash` · `ballad` · `coral` · `echo` · `fable` · `onyx` · `nova` · `sage` · `shimmer`

#### 나레이션 스타일 (narrationStyle)
`character` (캐릭터 음성) · `narrator` (내레이터) · `none` (없음)

#### 캐릭터 카테고리 (CharacterCategory)
`MEME`(밈/표정 캐릭터) · `ACTION`(액션 캐릭터) · `CUTE`(귀여운 캐릭터) · `BEAUTY`(인기 미남/미소녀)
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


_FIELD_NAMES_KR: dict[str, str] = {
    "idea": "아이디어",
    "title": "제목",
    "keyword": "키워드",
    "character_id": "캐릭터",
    "name": "이름",
    "description": "설명",
}


def _translate_error(field: str | None, msg: str) -> str:
    """Pydantic 에러 메시지를 한글로 변환"""
    field_kr = _FIELD_NAMES_KR.get(field or "", field or "입력값")

    if "at least" in msg:
        # "String should have at least 10 characters"
        import re
        m = re.search(r"at least (\d+)", msg)
        if m:
            return f"{field_kr}은(는) 최소 {m.group(1)}자 이상 입력해주세요."
    if "at most" in msg or "max_length" in msg:
        import re
        m = re.search(r"at most (\d+)", msg) or re.search(r"(\d+)", msg)
        if m:
            return f"{field_kr}은(는) 최대 {m.group(1)}자까지 입력 가능합니다."
    if "required" in msg.lower() or "missing" in msg.lower():
        return f"{field_kr}은(는) 필수 입력 항목입니다."
    if "none is not an allowed" in msg.lower():
        return f"{field_kr}을(를) 입력해주세요."
    return f"{field_kr}: {msg}"


@app.exception_handler(ValidationError)
async def validation_error_handler(request: Request, exc: ValidationError):
    """Pydantic 유효성 검사 에러를 상세 한글 메시지로 변환"""
    errors = []
    for error in exc.errors():
        field = ".".join(str(loc) for loc in error["loc"]) if error["loc"] else None
        kr_msg = _translate_error(field, error["msg"])
        errors.append({"field": field, "message": kr_msg})

    # 첫 번째 에러를 detail에 표시
    detail = errors[0]["message"] if errors else "입력값이 올바르지 않습니다."

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "detail": detail,
            "errors": errors,
        },
    )


app.include_router(api_router, prefix="/api")


@app.get("/health")
async def health_check():
    return {"status": "ok", "version": settings.VERSION}
