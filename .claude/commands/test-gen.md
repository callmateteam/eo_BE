# 테스트 자동 생성 스킬

변경된 코드 또는 지정된 모듈에 대한 테스트를 자동 생성합니다.

## 분석 대상 파악

```bash
cd /Users/intalk/Desktop/개인/eo/be && git diff --name-only HEAD 2>/dev/null || find app/ -name "*.py" -newer tests/ 2>/dev/null
```

## 현재 커버리지 확인

```bash
cd /Users/intalk/Desktop/개인/eo/be && source .venv/bin/activate && python -m pytest --cov=app --cov-report=term-missing -q 2>/dev/null
```

## 테스트 생성 규칙

변경된 각 파일에 대해 테스트를 생성하세요:

### API 엔드포인트 (app/api/)

- httpx.AsyncClient + ASGITransport 패턴 사용
- 정상 케이스 (200, 201)
- 입력 검증 실패 (422)
- 인증 필요 엔드포인트는 미인증 (401), 권한 없음 (403) 테스트
- 존재하지 않는 리소스 (404)

```python
# 패턴 예시
from httpx import ASGITransport, AsyncClient
from app.main import app

async def test_endpoint_success():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/resource", json={"field": "value"})
    assert response.status_code == 201
```

### 서비스 레이어 (app/services/)

- 비즈니스 로직의 정상/실패 경로 모두 테스트
- 외부 의존성은 모킹 (DB, AWS 등)
- 경계값 테스트

### 모델 (app/models/)

- 필수 필드 검증
- 관계(relationship) 검증
- 제약 조건 검증

## 테스트 파일 네이밍

- `app/api/users.py` → `tests/test_api_users.py`
- `app/services/auth.py` → `tests/test_services_auth.py`

## 생성 후 검증

```bash
cd /Users/intalk/Desktop/개인/eo/be && source .venv/bin/activate && python -m pytest -v --tb=short
```

새 테스트가 모두 통과하는지 확인하고, 실패 시 수정하세요.
