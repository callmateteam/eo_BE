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
cd /Users/intalk/Desktop/개인/eo/be && source .venv/bin/activate
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
