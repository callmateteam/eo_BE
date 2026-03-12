# 배포 전 체크리스트 스킬

프로덕션 배포 전 반드시 확인해야 할 항목들을 점검합니다.

## 1단계: 코드 상태 확인
```bash
cd /Users/intalk/Desktop/개인/eo/be && git status
```
```bash
cd /Users/intalk/Desktop/개인/eo/be && git log --oneline -5
```
- 커밋되지 않은 변경 사항 확인
- 최근 커밋 메시지 적절성 확인

## 2단계: 전체 테스트 실행
```bash
cd /Users/intalk/Desktop/개인/eo/be && python -m pytest --cov=app -v
```
- **모든 테스트 통과 필수**
- 커버리지 70% 이상 확인

## 3단계: 린트 및 포맷팅
```bash
cd /Users/intalk/Desktop/개인/eo/be && python -m ruff check . && python -m ruff format --check .
```

## 4단계: 보안 스캔
```bash
cd /Users/intalk/Desktop/개인/eo/be && python -m bandit -r app/ -ll
```

## 5단계: 환경 설정 검증
다음 항목을 확인하세요:

- [ ] `.env.example`에 모든 필수 환경변수가 문서화됨
- [ ] `DEBUG=false`로 설정 (프로덕션)
- [ ] `SECRET_KEY`가 안전한 랜덤 값
- [ ] `DATABASE_URL`이 프로덕션 DB를 가리킴
- [ ] `ALLOWED_ORIGINS`가 실제 프론트엔드 도메인만 포함
- [ ] AWS 자격증명이 환경변수/IAM 역할로 설정됨

## 6단계: 도커/인프라 확인
```bash
cd /Users/intalk/Desktop/개인/eo/be && test -f Dockerfile && echo "Dockerfile 존재" || echo "Dockerfile 없음"
```
```bash
cd /Users/intalk/Desktop/개인/eo/be && test -f docker-compose.yml && echo "docker-compose.yml 존재" || echo "docker-compose.yml 없음"
```

## 7단계: API 문서 확인
- `/docs` (Swagger) 접근 가능한지 확인
- 모든 엔드포인트에 적절한 응답 스키마가 정의되었는지 확인

## 배포 판정
| 항목 | 상태 |
|------|------|
| 테스트 전체 통과 | ✅/❌ |
| 린트 통과 | ✅/❌ |
| 보안 스캔 통과 | ✅/❌ |
| 환경 설정 완료 | ✅/❌ |
| 인프라 준비 | ✅/❌ |

**모든 항목이 ✅일 때만 배포를 진행하세요.**
