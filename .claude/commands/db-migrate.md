# DB 마이그레이션 가이드 스킬

Alembic을 사용한 데이터베이스 마이그레이션을 안내합니다.

## 현재 상태 확인
```bash
cd /Users/intalk/Desktop/개인/eo/be && python -m alembic current 2>/dev/null || echo "Alembic 초기화 필요: python -m alembic init alembic"
```
```bash
cd /Users/intalk/Desktop/개인/eo/be && python -m alembic history --verbose 2>/dev/null | head -20
```

## 마이그레이션 생성 가이드

### 자동 생성 (모델 변경 감지)
```bash
cd /Users/intalk/Desktop/개인/eo/be && python -m alembic revision --autogenerate -m "설명"
```

### 수동 생성
```bash
cd /Users/intalk/Desktop/개인/eo/be && python -m alembic revision -m "설명"
```

## 마이그레이션 체크리스트

생성된 마이그레이션 파일을 다음 관점에서 검토하세요:

- [ ] **데이터 손실**: DROP COLUMN, DROP TABLE이 의도적인가?
- [ ] **다운타임**: 대용량 테이블에 ALTER TABLE은 잠금 발생 가능
- [ ] **롤백 가능**: downgrade()가 올바르게 작성되었는가?
- [ ] **인덱스**: 자주 조회하는 컬럼에 인덱스 추가
- [ ] **NOT NULL**: 기존 데이터에 NULL이 있으면 DEFAULT 값 필요
- [ ] **외래 키**: CASCADE 설정이 적절한가?

## 마이그레이션 적용
```bash
cd /Users/intalk/Desktop/개인/eo/be && python -m alembic upgrade head
```

## 롤백
```bash
cd /Users/intalk/Desktop/개인/eo/be && python -m alembic downgrade -1
```

## 주의사항
- **프로덕션 마이그레이션은 반드시 백업 후 진행**
- 대용량 테이블 변경은 오프피크 시간에 수행
- 마이그레이션 파일은 반드시 코드 리뷰 (`/project:review`) 후 적용
