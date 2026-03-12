# API 엔드포인트 스캐폴딩 스킬

새 리소스에 대한 CRUD API를 자동으로 스캐폴딩합니다.
사용자가 리소스 이름을 제공하면 전체 구조를 생성합니다.

## 사용법

`/project:api-gen` 실행 후 리소스 이름을 입력하세요.
예: "user", "product", "order"

## 생성 순서 (ORCHESTRATION.md Phase 3 준수)

### Step 1: Pydantic 스키마 (app/schemas/)

```python
# app/schemas/{resource}.py
from pydantic import BaseModel, ConfigDict

class {Resource}Base(BaseModel):
    # 공통 필드

class {Resource}Create({Resource}Base):
    # 생성 시 필요한 필드

class {Resource}Update(BaseModel):
    # 업데이트 시 옵셔널 필드

class {Resource}Response({Resource}Base):
    model_config = ConfigDict(from_attributes=True)
    id: int
```

### Step 2: SQLAlchemy 모델 (app/models/)

```python
# app/models/{resource}.py
from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.orm import DeclarativeBase

class {Resource}(Base):
    __tablename__ = "{resource}s"
    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())
```

### Step 3: 서비스 레이어 (app/services/)

```python
# app/services/{resource}.py
# CRUD 비즈니스 로직
# - create_{resource}
# - get_{resource}
# - get_{resource}s (리스트 + 페이지네이션)
# - update_{resource}
# - delete_{resource}
```

### Step 4: API 라우터 (app/api/)

```python
# app/api/{resource}.py
# RESTful 엔드포인트
# - POST   /api/{resource}s       (생성)
# - GET    /api/{resource}s       (목록)
# - GET    /api/{resource}s/{id}  (조회)
# - PATCH  /api/{resource}s/{id}  (수정)
# - DELETE /api/{resource}s/{id}  (삭제)
```

### Step 5: 테스트 (tests/)

```python
# tests/test_api_{resource}.py
# 각 엔드포인트별 테스트
```

## 생성 후 작업

1. `app/api/__init__.py`에 새 라우터 등록
2. Alembic 마이그레이션 생성: `alembic revision --autogenerate -m "add {resource}"`
3. 테스트 실행: `python -m pytest tests/test_api_{resource}.py -v`
