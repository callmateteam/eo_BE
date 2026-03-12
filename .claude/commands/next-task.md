# 자동 태스크 발견 스킬 (/project:next-task)

AgentSys의 next-task 패턴을 적용합니다.
프로젝트에서 다음에 해야 할 작업을 자동으로 발견하고 우선순위를 매깁니다.

## 1단계: MEMORY.md 확인

MEMORY.md의 다음 섹션을 확인하세요:

- 기술 부채 추적
- 알려진 이슈

## 2단계: 코드 내 TODO/FIXME 탐색

```bash
cd /Users/intalk/Desktop/개인/eo/be && grep -rn "TODO\|FIXME\|HACK\|XXX\|WARN" app/ tests/ --include="*.py" 2>/dev/null
```

## 3단계: 테스트 커버리지 분석

```bash
cd /Users/intalk/Desktop/개인/eo/be && source .venv/bin/activate && python -m pytest --cov=app --cov-report=term-missing -q 2>/dev/null
```

커버리지 70% 미만 모듈을 식별하세요.

## 4단계: 보안 이슈 확인

```bash
cd /Users/intalk/Desktop/개인/eo/be && source .venv/bin/activate && bandit -r app/ -ll -q 2>/dev/null
```

## 5단계: 빈 모듈 확인

```bash
cd /Users/intalk/Desktop/개인/eo/be && find app/ -name "*.py" -empty -o -name "*.py" -size 1c | grep -v __pycache__
```

```bash
cd /Users/intalk/Desktop/개인/eo/be && wc -l app/**/*.py 2>/dev/null | sort -n | head -10
```

## 6단계: 우선순위 매기기

발견된 태스크를 다음 우선순위로 정렬하세요:

1. **CRITICAL**: 보안 이슈 (즉시 수정)
2. **HIGH**: 버그, 테스트 실패
3. **MEDIUM**: 테스트 커버리지 부족, TODO/FIXME
4. **LOW**: 코드 개선, 리팩토링

## 7단계: 태스크 리스트 출력

| 우선순위 | 태스크 | 파일 | 설명 |
|---------|--------|------|------|
| 1 | ... | ... | ... |
| 2 | ... | ... | ... |
| 3 | ... | ... | ... |

## 8단계: 다음 작업 제안

가장 우선순위가 높은 태스크를 선택하여 다음을 제시하세요:

- 무엇을 해야 하는지
- 어떤 파일을 수정해야 하는지
- 예상 접근 방식

사용자가 승인하면 ORCHESTRATION.md의 기능 개발 파이프라인을 자동 시작합니다.
