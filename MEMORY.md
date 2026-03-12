# EO Backend - 프로젝트 메모리

> 크로스 세션 메모리 시스템. 세션 간 상태를 유지합니다.
> 이 파일은 자동으로 업데이트됩니다. 수동 편집도 가능합니다.

---

## 프로젝트 결정 사항

### 아키텍처 결정

- **2026-03-12**: FastAPI + SQLAlchemy 2.0 async 채택
- **2026-03-12**: AWS ap-northeast-2 리전 선택
- **2026-03-12**: JWT HS256 인증 방식 채택 (만료 30분)

### 기술 부채 추적

_(아직 없음 - 발견 시 여기에 기록)_

### 알려진 이슈

_(아직 없음 - 발견 시 여기에 기록)_

---

## 세션 히스토리

### 2026-03-12 (초기 세팅)

- FastAPI 프로젝트 구조 생성
- Claude Code 스킬 시스템 구축 (QA, 보안, 배포, DB, 모니터링)
- 멀티 에이전트 시스템 설계 (7개 에이전트)
- 오케스트레이션 워크플로우 정의
- 테스트 2/2 통과, 린트 클린

---

## 환경 메모

- Python: 3.9.6 (로컬) / 3.11+ (프로덕션 타겟)
- venv 위치: `/Users/intalk/Desktop/개인/eo/be/.venv`
- 활성화: `source .venv/bin/activate`

---

## 자주 쓰는 커맨드

```bash
# 서버 실행
uvicorn app.main:app --reload

# 테스트
python -m pytest --cov=app -v

# 린트
ruff check --fix . && ruff format .

# 보안 스캔
bandit -r app/ -ll
```

---

## 학습된 패턴

- `safety` 패키지는 pydantic 2.10+ 과 버전 충돌 → requirements.txt에서 제외함
- ruff UP017 룰은 Python 3.9 환경에서 `datetime.UTC` 미지원 → auto-fix로 해결됨
