# EO Backend - Claude Code 마스터 설정

> 이 파일은 세션 초기화 시 자동으로 로드됩니다.
> 모든 에이전트, 스킬, 오케스트레이션의 진입점입니다.

## 프로젝트 개요
- **스택**: Python 3.11+ / FastAPI / SQLAlchemy 2.0 (async) / PostgreSQL
- **인프라**: AWS ap-northeast-2 (EC2, RDS, S3, CloudWatch)
- **철학**: 코드는 코드 일, AI는 AI 일 (AgentSys 원칙)

## 핵심 파일 참조
| 파일 | 역할 |
|------|------|
| `CLAUDE.md` | 세션 초기화, 규칙, 스킬 인덱스 (이 파일) |
| `AGENTS.md` | 멀티 에이전트 정의 및 역할 배정 |
| `MEMORY.md` | 크로스 세션 프로젝트 메모리 |
| `ORCHESTRATION.md` | 워크플로우 파이프라인 및 페이즈 게이트 |

---

## 절대 규칙 (위반 불가)
1. `.env`, 시크릿, AWS 키는 **절대** 코드/커밋에 포함 금지
2. SQL 쿼리는 **반드시** 파라미터 바인딩 (`bindparams`) 사용
3. 모든 사용자 입력은 **Pydantic 모델**로 검증
4. 보안 이슈 (severity HIGH)는 **즉시 수정** - 배포 차단
5. 테스트 없는 코드는 **머지 금지**
6. 에이전트 간 작업 시 **ORCHESTRATION.md 페이즈 게이트** 준수

## 개발 규칙

### 코드 스타일
- `ruff check --fix . && ruff format .`
- 라인 길이 100자 / 타입 힌트 필수 / docstring 한글

### 보안 기본 정책
- CORS: 명시적 origin만 허용 (와일드카드 금지)
- JWT: 만료 30분 이내 / HS256
- 비밀번호: bcrypt 해싱
- AWS: IAM 최소 권한 / 환경변수만 사용

### 테스트
```bash
cd /c/Users/somem/Desktop/해커톤/eo_BE && source .venv/Scripts/activate
python -m pytest --cov=app --cov-report=term-missing -v
```

### 프로젝트 구조
```
be/
├── CLAUDE.md              # 마스터 설정 (이 파일)
├── AGENTS.md              # 멀티 에이전트 정의
├── MEMORY.md              # 프로젝트 메모리
├── ORCHESTRATION.md       # 워크플로우 오케스트레이션
├── app/
│   ├── main.py            # FastAPI 엔트리포인트
│   ├── core/              # 설정, 보안, DB
│   ├── api/               # 라우터
│   ├── models/            # SQLAlchemy 모델
│   ├── schemas/           # Pydantic 스키마
│   └── services/          # 비즈니스 로직
├── tests/                 # 테스트
├── .claude/
│   ├── commands/          # 스킬 (슬래시 커맨드)
│   └── settings.json      # 훅 및 자동화 설정
└── docker-compose.yml
```

---

## 스킬 인덱스 (슬래시 커맨드)

### QA & 테스트
| 커맨드 | 설명 |
|--------|------|
| `/project:qa` | 전체 QA (린트 + 보안 + 테스트 + 리포트) |
| `/project:review` | 코드 리뷰 (git diff 기반) |
| `/project:test-gen` | 테스트 자동 생성 |

### 보안
| 커맨드 | 설명 |
|--------|------|
| `/project:security` | AWS 보안 + 코드 보안 종합 감사 |
| `/project:vuln-scan` | 의존성 취약점 스캔 |
| `/project:secret-scan` | 시크릿/키 누출 탐지 |

### 인프라 & 배포
| 커맨드 | 설명 |
|--------|------|
| `/project:deploy-check` | 배포 전 체크리스트 |
| `/project:aws-audit` | AWS 리소스 보안 감사 |
| `/project:monitor` | 서버 모니터링/로그 분석 |

### 개발
| 커맨드 | 설명 |
|--------|------|
| `/project:db-migrate` | DB 마이그레이션 가이드 |
| `/project:api-gen` | API 엔드포인트 스캐폴딩 |
| `/project:perf` | 성능 프로파일링 |

### 오케스트레이션
| 커맨드 | 설명 |
|--------|------|
| `/project:ship` | 전체 배포 파이프라인 (테스트→리뷰→보안→배포) |
| `/project:next-task` | 자동 태스크 발견 및 실행 |

---

## 에이전트 자동 선택 규칙
작업 유형에 따라 AGENTS.md에 정의된 에이전트가 자동 활성화됩니다:
- **코드 작성** → `implementation-agent`
- **보안 관련** → `security-agent`
- **테스트 작성** → `qa-agent`
- **인프라/AWS** → `infra-agent`
- **코드 리뷰** → `review-agent`
- **성능 이슈** → `perf-agent`

자세한 에이전트 정의는 `AGENTS.md`를 참조하세요.

---

## 프로젝트 화면 기능 스펙 (구현 대상)

> 아래 스펙을 단계별로 구현할 것. 각 단계는 독립적으로 완성 가능하게 구현.
> ORM은 Prisma (prisma/schema.prisma), DB는 PostgreSQL.

### 현재 구현 상태

**이미 있는 것 (수정/확장 필요):**
- `Project` 모델: title, keyword, status, characterId, userId (prisma/schema.prisma)
- `Project` CRUD API: POST/GET/DELETE /api/projects (app/api/project.py)
- `Project` 서비스: create, list, get, delete (app/services/project.py)
- `Project` 스키마: ProjectStatus(CREATED~COMPLETED) (app/schemas/project.py)
- `Storyboard` 모델: idea, scenes, status, heroFrameUrl 등
- `StoryboardScene` 모델: title, content, imagePrompt, imageUrl, videoUrl 등
- `CustomCharacter` 모델: name, description, style(enum), imageUrl1/2, voiceId, voiceStyle
- 스토리보드 생성/씬 수정/이미지 재생성/영상 생성 API 전부 있음
- WebSocket: 커스텀캐릭터 진행률, 스토리보드 진행률, 영상 진행률 전부 있음

**새로 만들거나 크게 수정해야 할 것:**
- Project에 **4단계 트래킹** + **임시저장 스냅샷** 기능 추가
- Project와 Storyboard 연결 (현재 독립적)
- 프로젝트 **수정(PATCH)** API 추가
- 프로젝트 리스트에 **썸네일, 캐릭터명** 포함
- 2가지 생성 경로 분기 로직

---

### 프로젝트 리스트 화면

**API**: `GET /api/projects`

응답에 포함할 필드:
- 프로젝트 ID, 제목
- 썸네일 (스토리보드 heroFrameUrl 또는 첫 번째 씬 imageUrl)
- 캐릭터 이름 (프리셋 Character.name 또는 CustomCharacter.name)
- 현재 단계 (1~4)
- 생성일, 수정일

**CRUD**:
- `POST /api/projects` - 생성 (캐릭터 선택 또는 신규 생성 경로 분기)
- `PATCH /api/projects/{id}` - 수정
- `DELETE /api/projects/{id}` - 삭제 (연관 스토리보드/영상 cascade)

---

### 4단계 트래킹 시스템

프로젝트는 4단계를 순서대로 진행하며, 각 단계의 데이터를 DB에 저장한다.
수정 시 저장된 단계부터 이어서 시작할 수 있다.

| 단계 | 이름 | 설명 | 저장 데이터 |
|------|------|------|------------|
| 1 | CHARACTER_SELECT | 캐릭터 생성 또는 선택 | character_id 또는 custom_character_id |
| 2 | IDEA_INPUT | 아이디어 입력 | idea 텍스트 |
| 3 | IDEA_ENRICHMENT | 아이디어 구체화 (GPT → 사용자 수정) | enrichedIdea (JSON: background, mood, main_character, supporting_characters, story) |
| 4 | STORYBOARD | 스토리보드(콘티) 생성/수정 | storyboard_id + scenes 데이터 |
| 5 | VIDEO_GENERATION | 영상 생성 및 편집 | 각 씬 videoUrl, finalVideoUrl |

**DB 변경 (prisma/schema.prisma):**
```
// Project 모델 수정
model Project {
  id                 String    @id @default(uuid())
  title              String
  currentStage       Int       @default(1)    // 1~4
  characterId        String?                  // 프리셋 캐릭터
  customCharacterId  String?                  // 커스텀 캐릭터
  storyboardId       String?   @unique        // 연결된 스토리보드
  idea               String?                  // 2단계: 아이디어 텍스트
  userId             String
  // relations, timestamps 등
}
```

- `currentStage`: 마지막으로 완료한 단계 (1~4)
- 수정 시 `currentStage` 값을 보고 해당 단계의 화면부터 시작
- 각 단계 완료 시 `currentStage` 증가 + 관련 데이터 저장

---

### 2가지 생성 경로

#### 경로 A: 기존 캐릭터 선택 → 영상 제작
1. 사용자가 프리셋/커스텀 캐릭터 선택
2. `POST /api/projects` → characterId 또는 customCharacterId 전달
3. **currentStage = 1 (CHARACTER_SELECT 완료)** 으로 저장
4. 바로 2단계(아이디어 입력)로 이동

#### 경로 B: 새 캐릭터 생성 → 영상 제작
1. 사용자가 커스텀 캐릭터 생성 (기존 `POST /api/characters/custom` 활용)
2. WS로 진행률 수신, 완료 시 customCharacterId 획득
3. `POST /api/projects` → customCharacterId 전달
4. **currentStage = 1** 로 저장
5. 2단계로 이동

---

### 단계별 상세

#### 1단계: 캐릭터 생성/선택 (CHARACTER_SELECT)

**기존 캐릭터 선택 시:**
- 기존 API 사용: `GET /api/characters`, `GET /api/characters/custom`

**신규 캐릭터 생성 시 (기존 API 활용):**
- `POST /api/characters/custom` (multipart/form-data)
  - 입력: 이미지 2장, 캐릭터 이름, 설명, style(enum), voiceId(enum)
  - style enum: REALISTIC, ANIME, CARTOON_3D, ILLUSTRATION_2D, CLAY, WATERCOLOR
  - voiceId enum: alloy, ash, ballad, coral, echo, fable, onyx, nova, sage, shimmer
- `WS /api/characters/custom/ws/{character_id}` → 진행률 % 수신
- 완성 후 캐릭터 이미지 표시
- 마음에 안 들면: 설명/스타일/음성 변경 → 이미지 재생성
- "캐릭터 등록" 버튼 → 캐릭터 확정, 프로젝트에 연결

#### 2단계: 아이디어 입력 (IDEA_INPUT)

- 선택된 캐릭터 정보를 DB에서 전체 조회 (그림체, 이미지URL, S3 에셋 등)
- 사용자가 아이디어 텍스트 입력
- `PATCH /api/projects/{id}` → idea 저장, currentStage = 2
- 다음 단계(스토리보드 생성)로 이동

#### 3단계: 스토리보드(콘티) 생성 (STORYBOARD)

**콘티 생성 (기존 API 활용):**
- `POST /api/storyboards` → character_id + idea 전달
- GPT가 3~5장의 콘티 생성
- `WS /api/storyboards/ws/{storyboard_id}` → 생성 진행률 수신

**콘티 리스트 표시:**
- 각 씬마다: 썸네일(imageUrl), 씬 제목(title), 씬 설명(content)
- 리스트로 보여주고, 클릭 시 상세 보기

**콘티 상세:**
- 썸네일, 제목, 전체 내용(content), imagePrompt 등 모든 정보 표시
- 수정 가능: 제목, 내용 → `PATCH /api/storyboards/{id}/scenes/{scene_id}`
- 내용 수정 시 imageStatus = STALE → 이미지 재생성 필요
- 이미지 재생성: `POST /api/storyboards/{id}/scenes/{scene_id}/regenerate-image`
- 재생성된 이미지가 마음에 들면 저장 → 영상 생성 시 이 이미지 사용

**완료 시:**
- `PATCH /api/projects/{id}` → storyboardId 연결, currentStage = 3

#### 4단계: 영상 생성 및 편집 (VIDEO_GENERATION)

**영상 생성 (기존 API 활용):**
- `POST /api/storyboards/{id}/generate-videos` → 전체 씬 영상 생성 시작
- `WS /api/storyboards/ws/{storyboard_id}/video` → 씬별 진행률 수신
- 콘티별로 영상 생성 (씬 설명 → 프롬프트 변환 → 영상 API 호출)
- 백그라운드에서 제작, 완료 시 WS 알림

**프롬프트 처리:**
- 사용자에게는 "장면 설명"으로 보여줌
- 내부 로직에서는 prompt_optimizer.py로 영상 생성용 프롬프트로 변환
- 캐릭터 veoPrompt + 씬 content + 스타일 힌트 결합

**완료 시:**
- `PATCH /api/projects/{id}` → currentStage = 4
- finalVideoUrl 저장

---

### 수정 플로우

- `GET /api/projects/{id}` → currentStage 확인
- currentStage에 해당하는 화면으로 이동
- 해당 단계에 이미 저장된 데이터를 불러와서 표시
- 생성 플로우와 동일하게 수정 가능 (콘티 설명, 썸네일, 제목 등)
- 이전 단계로 돌아가서 수정 가능 (예: 3단계에서 2단계로 돌아가 아이디어 변경)

---

---

## 영상 편집 기능 스펙 (4단계: VIDEO_GENERATION 내 편집)

> 영상 생성이 완료된 후, 사용자가 최종 영상을 편집할 수 있는 기능.
> 편집 상태는 DB에 JSON으로 저장되며, 최종 렌더링은 ffmpeg로 처리.
> 되돌리기(Undo)는 히스토리 스냅샷 기반.

### DB 모델 추가 (prisma/schema.prisma)

```prisma
model VideoEdit {
  id             String   @id @default(uuid())
  storyboardId   String   @unique
  storyboard     Storyboard @relation(fields: [storyboardId], references: [id], onDelete: Cascade)
  editData       Json     // 전체 편집 상태 (아래 JSON 구조 참고)
  version        Int      @default(1)
  userId         String
  user           User     @relation(fields: [userId], references: [id])
  createdAt      DateTime @default(now())
  updatedAt      DateTime @updatedAt
}

model VideoEditHistory {
  id         String   @id @default(uuid())
  editId     String
  version    Int
  editData   Json     // 해당 시점의 전체 스냅샷
  createdAt  DateTime @default(now())

  @@index([editId, version])
}
```

### editData JSON 구조

```json
{
  "scenes": [
    {
      "scene_id": "uuid",
      "order": 1,
      "trim_start": 0.000,
      "trim_end": 5.000,
      "speed": 1.0,
      "transition": "none",
      "audio": {
        "mute_ranges": [[1.200, 2.500]],
        "volume_ranges": [{"start": 0.0, "end": 5.0, "volume": 1.0}]
      }
    }
  ],
  "bgm": {
    "preset": "energetic",
    "custom_url": null,
    "volume": 0.2
  },
  "subtitles": [
    {
      "scene_id": "uuid",
      "text": "자막 텍스트",
      "start": 0.000,
      "end": 3.000,
      "style": {
        "font": "NanumGothic",
        "font_size": 24,
        "color": "#FFFFFF",
        "shadow": {"enabled": true, "color": "#000000", "offset": 2},
        "background": {"enabled": true, "color": "#000000", "opacity": 0.7},
        "position": "bottom",
        "position_y": null,
        "animation": "none",
        "per_char_sizes": null
      }
    }
  ],
  "tts_overlays": [
    {
      "id": "uuid",
      "text": "사용자가 입력한 TTS 텍스트",
      "voice_id": "alloy",
      "voice_style": "",
      "start": 2.500,
      "scene_id": "uuid",
      "audio_url": null
    }
  ],
  "thumbnail_time": 0.0
}
```

### API 엔드포인트

#### 편집 상태 CRUD
- `GET /api/storyboards/{id}/edit` — 편집 상태 조회 (없으면 초기값 자동 생성)
- `PATCH /api/storyboards/{id}/edit` — 편집 저장 (version 증가 + 히스토리 자동 생성)
- `POST /api/storyboards/{id}/edit/undo` — 한 단계 되돌리기 (이전 version의 히스토리 복원)

#### 커스텀 TTS 생성
- `POST /api/storyboards/{id}/edit/tts` — 사용자 입력 텍스트로 TTS 생성 → audio_url 반환
  - body: `{ "text": "...", "voice_id": "alloy", "voice_style": "" }`
  - 응답: `{ "audio_url": "s3://...", "duration": 3.5 }`

#### 최종 렌더링
- `POST /api/storyboards/{id}/render` — editData 기반 최종 영상 렌더링 (202 Accepted)
- `WS /api/storyboards/ws/{id}/render` — 렌더링 진행률 (ffmpeg 단계별)

#### 썸네일 추출
- `POST /api/storyboards/{id}/thumbnail` — 지정 시간의 프레임을 썸네일로 추출
  - body: `{ "time": 2.5 }`
  - 응답: `{ "thumbnail_url": "s3://..." }`

### 편집 기능 상세

#### 1. 타임라인 (0.001ms 정밀도)
- `trim_start`, `trim_end`: 씬별 시작/끝점 (float, 소수점 3자리)
- 프론트에서 타임라인 UI, 백엔드는 ffmpeg `-ss`/`-to` 옵션으로 처리

#### 2. 씬 순서 변경
- `editData.scenes[].order` 값 변경
- 프론트: 드래그앤드롭, 백엔드: order 기준 concat

#### 3. 씬 트림/컷
- `trim_start`, `trim_end` 조절
- ffmpeg: `-ss {trim_start} -to {trim_end}`

#### 4. 씬 간 전환 효과 (5종)
- `transition` 값: `none`, `fade`, `dissolve`, `slide_left`, `slide_up`, `wipe`
- ffmpeg: `xfade` 필터 (duration=0.5초 기본)

#### 5. 배속 조절
- `speed`: 0.5 ~ 2.0
- ffmpeg: `setpts={1/speed}*PTS` + `atempo={speed}`

#### 6. 구간 음소거 / 소리 증폭
- `mute_ranges`: [[시작, 끝], ...] — 해당 구간 volume=0
- `volume_ranges`: [{"start", "end", "volume"}] — 구간별 볼륨 (0.0~3.0)
- ffmpeg: `volume` 필터 + `enable='between(t,start,end)'`

#### 7. BGM 변경
- `bgm.preset`: 프리셋 선택 (energetic, calm, dramatic, happy, sad, mysterious, epic, romantic, funny, horror)
- `bgm.custom_url`: 사용자 업로드 BGM (추후)
- `bgm.volume`: 0.0 ~ 1.0

#### 8. 자막 편집
- **폰트 8종**: NanumGothic, NanumMyeongjo, NanumSquareRound, NanumBarunGothic, MapoFlowerIsland, GmarketSans, Pretendard, DoHyeon
- **글자 색상**: hex color (`#FFFFFF`)
- **글자 사이즈**: 정수 (12~72), `per_char_sizes`로 글자별 개별 사이즈 지정 가능
- **자막 배경**: enabled(on/off), color(hex), opacity(0.0~1.0)
- **그림자**: enabled(on/off), color(hex), offset(1~5px)
- **위치**: `position` = top/center/bottom 또는 `position_y` = 자유 배치 (0~100%)
- ffmpeg: ASS 자막 포맷으로 변환 → `subtitles` 필터

#### 9. 자막 애니메이션 (3종)
- `animation` 값: `none`, `typing`, `popup`, `fadein`
- ffmpeg ASS: `\fad`, `\move`, `\t` 태그로 구현

#### 10. 커스텀 TTS 오버레이
- 사용자가 원하는 텍스트를 입력 → TTS 생성 → 원하는 시점에 삽입
- `tts_overlays[].start`: 삽입 시작 시간
- `tts_overlays[].audio_url`: 생성된 TTS MP3 URL
- 기존 나레이션과 별개로 추가 가능
- ffmpeg: `adelay` 필터로 시점 맞춤 믹스

#### 11. 썸네일 선택
- `thumbnail_time`: 영상 내 특정 시간 (초)
- ffmpeg: `-ss {time} -frames:v 1` 으로 프레임 추출 → S3 업로드

### 렌더링 파이프라인 (ffmpeg)

```
1. 씬별 트림 + 배속 적용
2. 씬 순서대로 전환 효과 적용하며 concat
3. 구간별 음소거/볼륨 조절
4. TTS 오버레이 믹스 (시점별 adelay)
5. BGM 믹스 (TTS 있으면 자동 덕킹)
6. ASS 자막 번인 (폰트/색상/배경/그림자/애니메이션)
7. 썸네일 프레임 추출
8. S3 업로드 → finalVideoUrl 업데이트
```

### 되돌리기 (Undo) 로직

- `PATCH /edit` 호출 시마다 현재 editData를 VideoEditHistory에 저장 + version++
- `POST /edit/undo` 호출 시 version-1의 히스토리에서 editData 복원
- 최대 50단계 히스토리 유지 (초과 시 가장 오래된 것 삭제)

---

---

### 알려진 이슈: 영상이 콘티(이미지)와 불일치하는 문제

> **심각도**: HIGH — 이미지 콘티는 만족스럽게 나오지만, 영상(Hailuo I2V)이 콘티와 크게 다름
> **상태**: 원인 분석 완료, 수정 필요

#### 증상
- 콘티 이미지: 카페 실내, 피카츄가 테이블에 앉아 메뉴 보는 장면 → **정확히 나옴**
- 생성된 영상: 캐릭터 변형, 배경 불일치, 콘티와 다른 동작

#### 원인 분석 (Hailuo 프롬프트 vs 이미지 프롬프트 비교)

**1. 장면 컨텍스트 누락 — Hailuo 프롬프트에 배경/장소 정보가 없음**
```
[이미지 프롬프트] A cozy cafe interior with warm lighting, sitting at a table with a menu.
[Hailuo 프롬프트] [Truck right] Wide establishing shot Scene set in 포켓몬 세계관.
                  Character shifts gaze between menu and window, ears twitching.
```
- 이미지 프롬프트: "cozy cafe interior, warm lighting" 명시
- Hailuo 프롬프트: "포켓몬 세계관"만 있고 **카페/실내/조명 정보 없음**
- `build_hailuo_prompt`가 `motionPrompt`만 사용하고 `imagePrompt`(장면 묘사)를 무시함

**2. world_context가 한글 — Hailuo 모델은 영어 프롬프트 최적화**
```
Scene set in 포켓몬 세계관  ← 한글, Hailuo가 해석 못함
```
- `world_context`가 DB에 한글로 저장됨 → 영어로 변환 필요

**3. enrichedIdea 미활용 — 배경/분위기 데이터가 영상 프롬프트에 반영 안 됨**
- 3단계에서 구체화한 배경("카페 내부, 따뜻한 조명, 비 오는 창밖")이 영상 프롬프트에 안 들어감
- `prompt_optimizer.py`가 `enrichedIdea`를 전혀 모름

**4. imagePrompt 완전 무시 — motionPrompt만 사용**
```python
# prompt_optimizer.py L203-206
if motion_prompt:
    parts.append(motion_prompt)      # motionPrompt만 사용
elif image_prompt:
    parts.append(image_prompt)       # motionPrompt 없을 때만 fallback
```
- motionPrompt는 동작만 설명 ("Character shifts gaze...")
- imagePrompt는 장면 전체 설명 ("cozy cafe interior...")
- **motionPrompt가 있으면 imagePrompt를 완전히 버림** → 장면 컨텍스트 소실

#### 해결 방향
1. `build_hailuo_prompt`에서 `motionPrompt`와 `imagePrompt`를 **모두** 사용
   - imagePrompt에서 배경/장소 키워드 추출 → 프롬프트 앞부분에 삽입
   - motionPrompt는 동작 부분으로 유지
2. `world_context`를 영어로 변환하여 전달
3. `enrichedIdea.background` + `enrichedIdea.mood`를 Hailuo 프롬프트에 반영
4. 캐릭터 외형 묘사 단어("번개", "전기")가 Hailuo 프롬프트에 들어가지 않도록 필터

#### 관련 파일
- `app/services/prompt_optimizer.py` — `build_hailuo_prompt()` 수정 대상
- `app/services/video_generation.py` — `_generate_scene_video()` enrichedIdea 전달
- `app/services/storyboard.py` — enrichedIdea를 콘티 생성 시 저장

---

### 로컬 테스트 제한사항: ffmpeg 미설치

> **영향 범위**: 자막, 더빙(TTS 오버레이), 영상 합본, 렌더링
> **상태**: 로컬에서 테스트 불가, EC2 서버에서만 동작 확인 가능

#### 테스트 못한 기능
| 기능 | API | 의존성 | 비고 |
|------|-----|--------|------|
| 영상 합본 (씬 병합) | `POST /storyboards/{id}/generate-videos` 내부 merge | ffmpeg (concat + crossfade) | 씬별 영상 생성은 성공, 합본만 실패 |
| 자막 번인 | `POST /storyboards/{id}/render` | ffmpeg (ASS 자막 필터) | editData의 subtitles 기반 |
| TTS 오버레이 | `POST /storyboards/{id}/edit/tts` + render | ffmpeg (adelay 믹스) | TTS 생성(OpenAI)은 가능, 오디오 믹싱 불가 |
| BGM 믹싱 | render 파이프라인 내부 | ffmpeg (amix + ducking) | BGM 프리셋 S3 다운로드도 실패 |
| 썸네일 프레임 추출 | `POST /storyboards/{id}/thumbnail` | ffmpeg (-ss -frames:v 1) | |
| 전환 효과 (fade/dissolve/wipe) | render 내부 | ffmpeg (xfade 필터) | |
| 배속 조절 | render 내부 | ffmpeg (setpts/atempo) | |

#### 로컬에서 테스트 완료된 기능
- 콘티 생성 (GPT 씬 분할 + FLUX 이미지 생성) ✓
- 아이디어 구체화 (GPT enrichment) ✓
- 씬별 영상 생성 (Hailuo I2V) ✓
- 이미지 재생성 (hero frame 참조 + 배경 일관성) ✓
- 프로젝트 5단계 트래킹 + stages 응답 ✓
- DB CRUD 전체 (SSH 터널 경유) ✓

#### 서버 테스트 시 확인할 것
1. `add_enriched_idea.sql` 마이그레이션 먼저 실행
2. ffmpeg 설치 확인: `which ffmpeg` (EC2에 이미 있을 수 있음)
3. BGM 프리셋 S3 접근: `s3://eo-character-assets/bgm/calm.mp3` 등
4. 전체 렌더링 파이프라인 E2E 테스트: 콘티 생성 → 영상 생성 → 편집 → 렌더링 → 다운로드

---

### 구현 순서 (세션별 1단계씩)

1. **DB 스키마 변경**: Project 모델에 currentStage, customCharacterId, storyboardId, idea 추가 → prisma migrate
2. **프로젝트 CRUD 확장**: PATCH API 추가, 리스트에 썸네일/캐릭터명 포함, 2가지 생성 경로 분기
3. **단계 트래킹 로직**: 각 단계 완료 시 currentStage 업데이트, 수정 시 해당 단계부터 재개
4. **프로젝트-스토리보드 연결**: Project.storyboardId 연결, 영상 완료 시 Project 상태 업데이트
5. **영상 편집 DB + API**: VideoEdit/VideoEditHistory 모델 + 편집 CRUD + Undo API
6. **커스텀 TTS API**: 사용자 입력 텍스트 → TTS 생성 → audio_url 반환
7. **렌더링 파이프라인**: editData → ffmpeg 렌더링 (트림/전환/배속/오디오/자막/썸네일)
8. **렌더링 WS**: 렌더링 진행률 실시간 전송
