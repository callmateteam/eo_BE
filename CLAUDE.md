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
| 3 | STORYBOARD | 스토리보드(콘티) 생성/수정 | storyboard_id + scenes 데이터 |
| 4 | VIDEO_GENERATION | 영상 생성 및 편집 | 각 씬 videoUrl, finalVideoUrl |

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

### 구현 순서 (세션별 1단계씩)

1. **DB 스키마 변경**: Project 모델에 currentStage, customCharacterId, storyboardId, idea 추가 → prisma migrate
2. **프로젝트 CRUD 확장**: PATCH API 추가, 리스트에 썸네일/캐릭터명 포함, 2가지 생성 경로 분기
3. **단계 트래킹 로직**: 각 단계 완료 시 currentStage 업데이트, 수정 시 해당 단계부터 재개
4. **프로젝트-스토리보드 연결**: Project.storyboardId 연결, 영상 완료 시 Project 상태 업데이트
