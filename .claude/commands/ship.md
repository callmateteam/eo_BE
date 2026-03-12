# 전체 배포 파이프라인 스킬 (/project:ship)

AgentSys의 ship 패턴을 적용한 전체 배포 파이프라인입니다.
ORCHESTRATION.md의 기능 개발 파이프라인 5단계를 자동 실행합니다.

## Phase 1: 현재 상태 확인

```bash
cd /Users/intalk/Desktop/개인/eo/be && git status && echo "---" && git log --oneline -5
```

커밋되지 않은 변경사항이 있으면 먼저 커밋 여부를 확인하세요.

## Phase 2: QA 게이트

### 린트 + 포맷

```bash
cd /Users/intalk/Desktop/개인/eo/be && source .venv/bin/activate && ruff check . && ruff format --check .
```

오류 시 자동 수정:

```bash
cd /Users/intalk/Desktop/개인/eo/be && source .venv/bin/activate && ruff check --fix . && ruff format .
```

### 테스트

```bash
cd /Users/intalk/Desktop/개인/eo/be && source .venv/bin/activate && python -m pytest --cov=app --cov-report=term-missing -v
```

**게이트 조건**: 테스트 100% 통과 + 린트 0 오류
실패 시 이슈를 수정하고 Phase 2를 재실행하세요.

## Phase 3: 보안 게이트

### 코드 보안

```bash
cd /Users/intalk/Desktop/개인/eo/be && source .venv/bin/activate && bandit -r app/ -ll -f json
```

### 시크릿 스캔

```bash
cd /Users/intalk/Desktop/개인/eo/be && grep -rn --include="*.py" -E "(AKIA|password\s*=\s*['\"][^'\"]{8,})" app/ | grep -v "__pycache__"
```

**게이트 조건**: HIGH 이슈 0건
HIGH 이슈 발견 시 **배포 차단** - 수정 후 Phase 2부터 재실행하세요.

## Phase 4: 빌드 확인

```bash
cd /Users/intalk/Desktop/개인/eo/be && test -f Dockerfile && docker build -t eo-backend:test . 2>&1 | tail -5 || echo "Dockerfile 없음 - 스킵"
```

## Phase 5: 배포 준비 리포트

### 파이프라인 결과

| Phase | 상태 | 비고 |
|-------|------|------|
| 1. 상태 확인 | ✅/❌ | |
| 2. QA 게이트 | ✅/❌ | 테스트 N개, 커버리지 N% |
| 3. 보안 게이트 | ✅/❌ | HIGH 이슈 N건 |
| 4. 빌드 확인 | ✅/❌ | |

### 배포 판정

- 모든 Phase ✅ → **배포 가능**
- 하나라도 ❌ → **배포 불가** (사유 명시)

배포 가능 판정 시, 사용자에게 다음 단계를 안내하세요:

```bash
# Docker 배포
docker-compose -f docker-compose.yml up -d --build

# 또는 직접 실행
uvicorn app.main:app --host 0.0.0.0 --port 8000
```
