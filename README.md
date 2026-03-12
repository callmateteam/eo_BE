# EO Backend

Python FastAPI 백엔드 + Claude Code 스킬 시스템

## Tech Stack

- **Python 3.11+** / FastAPI / SQLAlchemy 2.0 (async)
- **PostgreSQL 16** / Alembic (마이그레이션)
- **AWS** ap-northeast-2 (EC2, RDS, S3, CloudWatch)
- **Docker** / docker-compose

## Quick Start

```bash
# 가상환경 설정
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 서버 실행
uvicorn app.main:app --reload

# 테스트
python -m pytest --cov=app -v

# Docker
docker-compose up -d
```

## Project Structure

```
be/
├── CLAUDE.md              # Claude Code 마스터 설정
├── AGENTS.md              # 멀티 에이전트 정의 (7개)
├── MEMORY.md              # 크로스 세션 프로젝트 메모리
├── ORCHESTRATION.md       # 워크플로우 파이프라인
├── app/
│   ├── main.py            # FastAPI 엔트리포인트
│   ├── core/              # 설정, 보안, DB 연결
│   ├── api/               # API 라우터
│   ├── models/            # SQLAlchemy 모델
│   ├── schemas/           # Pydantic 스키마
│   └── services/          # 비즈니스 로직
├── tests/                 # pytest 테스트
├── .claude/
│   ├── commands/          # Claude Code 스킬 (14개)
│   └── settings.json      # 훅 및 권한 설정
├── Dockerfile
└── docker-compose.yml
```

## Claude Code Skills

[awesome-claude-code](https://github.com/hesreallyhim/awesome-claude-code)의 AgentSys, SuperClaude, Trail of Bits 패턴을 적용한 스킬 시스템입니다.

### QA & Testing

| Command | Description |
|---------|-------------|
| `/project:qa` | 전체 QA 점검 (린트 + 보안스캔 + 테스트 + 종합 리포트) |
| `/project:review` | 코드 리뷰 - git diff 기반, 보안/성능/품질 5개 관점 |
| `/project:test-gen` | 변경 코드에 대한 테스트 자동 생성 |

### Security

| Command | Description |
|---------|-------------|
| `/project:security` | AWS + 코드 보안 종합 감사 (Trail of Bits 패턴) |
| `/project:vuln-scan` | 의존성 취약점(CVE) 스캔 + 자동 업데이트 제안 |
| `/project:secret-scan` | 시크릿/AWS 키 누출 탐지 (코드 + git 히스토리) |
| `/project:aws-audit` | AWS IAM/EC2/RDS/S3/CloudWatch 보안 감사 |

### Infra & Deploy

| Command | Description |
|---------|-------------|
| `/project:deploy-check` | 배포 전 체크리스트 (테스트/린트/보안/환경설정/인프라) |
| `/project:monitor` | 서버 상태, 리소스 사용량, AWS 서비스 모니터링 |

### Development

| Command | Description |
|---------|-------------|
| `/project:db-migrate` | Alembic 마이그레이션 가이드 + 안전성 체크리스트 |
| `/project:api-gen` | CRUD API 스캐폴딩 (스키마 → 모델 → 서비스 → 라우터 → 테스트) |
| `/project:perf` | 성능 프로파일링 (N+1 쿼리, 비동기 분석, 캐싱 기회) |

### Orchestration

| Command | Description |
|---------|-------------|
| `/project:ship` | 전체 배포 파이프라인 - 5 Phase 자동 실행 (상태확인 → QA → 보안 → 빌드 → 배포) |
| `/project:next-task` | 자동 태스크 발견 - TODO/FIXME/커버리지/보안이슈 우선순위 정렬 |

### Recommended Workflow

```
코드 작성 → /project:qa → /project:review → /project:security → /project:ship
```

또는 한번에: `/project:ship` (전체 파이프라인 자동 실행)

## Multi-Agent System

7개 전문 에이전트가 작업 유형에 따라 자동 활성화됩니다 (상세: `AGENTS.md`):

| Agent | Role | Model |
|-------|------|-------|
| `security-agent` | 코드/AWS 보안 감사 | opus |
| `qa-agent` | 테스트, 린트, 커버리지 | sonnet |
| `implementation-agent` | FastAPI 코드 구현 | opus |
| `review-agent` | 코드 리뷰, 품질 판정 | opus |
| `infra-agent` | AWS, Docker, 배포 | sonnet |
| `perf-agent` | 성능 병목 분석 | sonnet |
| `db-agent` | 데이터 모델링, 마이그레이션 | sonnet |

## Orchestration Workflows

페이즈 게이트 기반 워크플로우 (상세: `ORCHESTRATION.md`):

1. **Feature Pipeline**: Research → Plan → Implement → Verify → Review
2. **Deploy Pipeline**: 코드 확인 → QA → 보안 → 인프라 → 승인
3. **Auto Task**: MEMORY → TODO 탐색 → 우선순위 → 제안 → 실행
4. **Security Audit**: 정적분석 → 코드감사 → 인프라감사 → 리포트

## Environment

```bash
cp .env.example .env
# .env 파일에 실제 값 설정
```

Required: `DATABASE_URL`, `SECRET_KEY`, `AWS_REGION`
