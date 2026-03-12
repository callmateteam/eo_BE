# 시크릿 누출 탐지 스킬

코드베이스와 git 히스토리에서 시크릿/키 누출을 탐지합니다.
Trail of Bits 보안 스킬 패턴을 적용합니다.

## 1단계: 코드 내 하드코딩된 시크릿 탐지

```bash
cd /Users/intalk/Desktop/개인/eo/be && grep -rn --include="*.py" --include="*.yaml" --include="*.yml" --include="*.json" --include="*.toml" --include="*.cfg" -E "(password|secret|token|api_key|apikey|access_key|private_key)\s*[=:]\s*['\"][^'\"]{8,}" . | grep -v ".git/" | grep -v "__pycache__" | grep -v ".venv/"
```

## 2단계: AWS 키 패턴 탐지

```bash
cd /Users/intalk/Desktop/개인/eo/be && grep -rn -E "(AKIA[0-9A-Z]{16}|[0-9a-zA-Z/+]{40})" . --include="*.py" --include="*.env*" --include="*.json" --include="*.yaml" | grep -v ".git/" | grep -v ".venv/"
```

## 3단계: .env 파일 보호 확인

```bash
cd /Users/intalk/Desktop/개인/eo/be && cat .gitignore | grep -E "\.env" || echo "경고: .env가 .gitignore에 없습니다!"
```

```bash
cd /Users/intalk/Desktop/개인/eo/be && git ls-files | grep -E "\.env$|\.pem$|\.key$|credentials" || echo "OK: 시크릿 파일이 추적되지 않음"
```

## 4단계: git 히스토리 시크릿 검사

```bash
cd /Users/intalk/Desktop/개인/eo/be && git log --all -p --diff-filter=A -- "*.env" "*.pem" "*.key" "*credential*" 2>/dev/null | head -50
```

```bash
cd /Users/intalk/Desktop/개인/eo/be && git log --all -p -S "AKIA" --since="6 months ago" 2>/dev/null | head -30
```

## 5단계: 설정 파일 검증

다음 파일들을 직접 읽어서 시크릿이 없는지 확인하세요:

- `app/core/config.py` - 기본값에 실제 시크릿이 없는지
- `docker-compose.yml` - 프로덕션 비밀번호가 없는지
- `alembic.ini` - DB URL에 실제 비밀번호가 없는지

## 리포트

| 위치 | 유형 | 심각도 | 상태 |
|------|------|--------|------|
| 코드 내 하드코딩 | 시크릿 | HIGH | ✅/❌ |
| AWS 키 패턴 | 자격증명 | CRITICAL | ✅/❌ |
| .gitignore 보호 | 설정 | HIGH | ✅/❌ |
| git 히스토리 | 시크릿 | CRITICAL | ✅/❌ |
| 설정 파일 | 시크릿 | HIGH | ✅/❌ |

CRITICAL 이슈 발견 시:
1. 즉시 해당 시크릿을 로테이션 (새 키 발급)
2. git 히스토리에서 제거 (`git filter-branch` 또는 BFG)
3. `.gitignore` 업데이트
