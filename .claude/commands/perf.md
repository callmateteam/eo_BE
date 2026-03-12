# 성능 프로파일링 스킬

코드의 성능 병목을 식별하고 최적화 방안을 제시합니다.
AgentSys 10단계 성능 조사 방법론을 적용합니다.

## 1단계: 쿼리 분석

app/ 디렉토리에서 SQLAlchemy 쿼리 패턴을 분석하세요:

```bash
cd /Users/intalk/Desktop/개인/eo/be && grep -rn "\.query\|select(\|\.filter\|\.join\|\.all()\|\.first()" app/ --include="*.py"
```

### N+1 쿼리 탐지

- 루프 내에서 DB 쿼리 호출하는 패턴 확인
- `selectinload`, `joinedload` 누락된 관계 확인
- 해결: eager loading 또는 단일 쿼리로 통합

### 인덱스 분석

- WHERE/JOIN에 사용되는 컬럼에 인덱스 존재 확인
- 복합 인덱스 필요 여부 판단

## 2단계: 비동기 분석

```bash
cd /Users/intalk/Desktop/개인/eo/be && grep -rn "def [a-z]" app/api/ --include="*.py" | grep -v "async def"
```

### 체크 항목

- API 핸들러가 `async def`인지 확인
- `await` 누락된 비동기 호출 탐지
- 동기 블로킹 호출 (requests, time.sleep) 탐지

```bash
cd /Users/intalk/Desktop/개인/eo/be && grep -rn "import requests\|time\.sleep\|open(" app/ --include="*.py"
```

## 3단계: 직렬화 분석

- Pydantic 모델의 불필요한 필드 변환 확인
- 대량 데이터 응답 시 페이지네이션 확인
- `response_model_exclude_unset=True` 활용 여부

## 4단계: 커넥션 관리

- DB 커넥션 풀 설정 확인 (pool_size, max_overflow)
- HTTP 클라이언트 세션 재사용 확인
- 커넥션 리크 가능성 점검

## 5단계: 캐싱 기회

- 반복 조회되는 정적 데이터 식별
- 설정값, 코드 테이블 등 캐시 후보
- Redis/인메모리 캐시 적용 가능 지점

## 성능 리포트

| 영역 | 상태 | 영향도 | 개선안 |
|------|------|--------|--------|
| N+1 쿼리 | ✅/❌ | 높음 | |
| 인덱스 | ✅/❌ | 높음 | |
| 비동기 처리 | ✅/❌ | 중간 | |
| 직렬화 | ✅/❌ | 낮음 | |
| 커넥션 관리 | ✅/❌ | 높음 | |
| 캐싱 | ✅/❌ | 중간 | |
