# AWS 보안 및 코드 보안 감사 스킬

프로젝트의 보안 상태를 종합적으로 감사합니다. **매 배포 전 반드시 실행하세요.**

## 1단계: 코드 보안 스캔

### Bandit 정적 분석
```bash
cd /Users/intalk/Desktop/개인/eo/be && python -m bandit -r app/ -ll -f json
```

### 수동 보안 체크리스트
아래 항목을 코드에서 직접 확인하세요:

- [ ] **SQL 인젝션**: 모든 쿼리가 파라미터 바인딩 사용하는지 확인
  - `text()` 사용 시 반드시 `.bindparams()` 체크
  - f-string이나 format으로 SQL 조합하는 코드가 없는지 확인
- [ ] **인증/인가**: 보호된 엔드포인트에 `Depends()` 가드 존재 확인
- [ ] **입력 검증**: 모든 request body/query param에 Pydantic 모델 사용
- [ ] **민감 정보 노출**: 로그, 에러 응답, traceback에 비밀 정보 없는지 확인
- [ ] **CORS 설정**: `allow_origins`가 와일드카드(`*`)가 아닌지 확인
- [ ] **JWT 설정**: 토큰 만료 시간이 적절한지 (30분 이내 권장)
- [ ] **비밀번호 해싱**: bcrypt 사용 확인, 평문 저장 없음

## 2단계: AWS 보안 감사

### 환경변수 및 시크릿
```bash
cd /Users/intalk/Desktop/개인/eo/be && grep -rn "AWS_\|aws_\|secret\|password\|token\|key" app/ --include="*.py" | grep -v "__pycache__" | grep -v ".pyc"
```
- AWS 키가 코드에 하드코딩되어 있지 않은지 확인
- `.env` 파일이 `.gitignore`에 포함되어 있는지 확인

### AWS 모범 사례 체크
- [ ] **IAM**: 최소 권한 원칙 (필요한 권한만 부여)
- [ ] **S3**: 퍼블릭 액세스 차단, 버킷 정책 검토
- [ ] **RDS**: 보안 그룹에서 0.0.0.0/0 허용 안 함
- [ ] **VPC**: 프라이빗 서브넷에 DB/내부 서비스 배치
- [ ] **SSL/TLS**: 모든 외부 통신에 HTTPS 사용
- [ ] **CloudWatch**: 이상 탐지 알람 설정
- [ ] **WAF**: 웹 애플리케이션 방화벽 활성화

### AWS 자격증명 검증
```bash
cd /Users/intalk/Desktop/개인/eo/be && grep -rn "AKIA\|amazonaws.com" . --include="*.py" --include="*.yaml" --include="*.yml" --include="*.json" --include="*.env*" | grep -v ".git/" | grep -v "__pycache__"
```
- `AKIA`로 시작하는 하드코딩된 AWS 액세스 키가 없는지 확인

## 3단계: 의존성 보안
```bash
cd /Users/intalk/Desktop/개인/eo/be && python -m pip_audit 2>/dev/null || echo "pip-audit 미설치 - pip install pip-audit 후 재실행"
```
```bash
cd /Users/intalk/Desktop/개인/eo/be && python -m safety check 2>/dev/null || echo "safety 미설치"
```

## 4단계: 시크릿 스캔
```bash
cd /Users/intalk/Desktop/개인/eo/be && git log --all --diff-filter=A -- "*.env" "*.pem" "*.key" "*credentials*" 2>/dev/null
```
- git 히스토리에 시크릿 파일이 커밋된 적 없는지 확인

## 5단계: 보안 감사 리포트

### 보안 감사 결과
| 영역 | 상태 | 심각도 | 비고 |
|------|------|--------|------|
| 코드 보안 (Bandit) | ✅/❌ | - | |
| SQL 인젝션 | ✅/❌ | 🔴 | |
| 인증/인가 | ✅/❌ | 🔴 | |
| 입력 검증 | ✅/❌ | 🟡 | |
| 민감 정보 노출 | ✅/❌ | 🔴 | |
| AWS 키 하드코딩 | ✅/❌ | 🔴 | |
| AWS IAM 최소 권한 | ✅/❌ | 🟡 | |
| 의존성 취약점 | ✅/❌ | 🟡 | |
| 시크릿 커밋 이력 | ✅/❌ | 🔴 | |

**🔴 높음 이슈가 있으면 즉시 수정하세요. 수정 전 배포는 금지합니다.**
