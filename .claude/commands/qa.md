# QA 전체 점검 스킬

프로젝트의 전체 품질을 점검합니다. 아래 단계를 순서대로 수행하세요.

## 1단계: 린트 검사
```bash
cd /Users/intalk/Desktop/개인/eo/be && python -m ruff check .
```
- 발견된 린트 오류를 모두 리포트
- 자동 수정 가능한 항목은 `ruff check --fix .`로 수정

## 2단계: 코드 포맷팅 확인
```bash
cd /Users/intalk/Desktop/개인/eo/be && python -m ruff format --check .
```
- 포맷팅이 안 된 파일이 있으면 `ruff format .`으로 수정

## 3단계: 보안 스캔 (bandit)
```bash
cd /Users/intalk/Desktop/개인/eo/be && python -m bandit -r app/ -f json
```
- severity가 MEDIUM 이상인 항목을 한글로 요약
- 각 이슈에 대한 수정 방안 제시

## 4단계: 테스트 실행
```bash
cd /Users/intalk/Desktop/개인/eo/be && python -m pytest --cov=app --cov-report=term-missing -v
```
- 실패한 테스트가 있으면 원인 분석 및 수정 제안
- 커버리지 80% 미만인 모듈 식별

## 5단계: 의존성 보안 점검
```bash
cd /Users/intalk/Desktop/개인/eo/be && python -m pip_audit 2>/dev/null || echo "pip-audit 미설치"
```

## 6단계: 종합 리포트
위 결과를 다음 형식으로 종합 요약하세요:

### QA 리포트
| 항목 | 상태 | 비고 |
|------|------|------|
| 린트 | ✅/❌ | 오류 N건 |
| 포맷팅 | ✅/❌ | |
| 보안 스캔 | ✅/❌ | 이슈 N건 |
| 테스트 | ✅/❌ | 통과율 N%, 커버리지 N% |
| 의존성 보안 | ✅/❌ | |

**심각도 높은 이슈**가 있으면 즉시 수정하고, 수정 후 해당 단계를 재실행하여 확인하세요.
