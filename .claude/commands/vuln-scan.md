# 의존성 취약점 스캔 스킬

설치된 패키지의 알려진 취약점(CVE)을 스캔합니다.

## 1단계: pip-audit 스캔

```bash
cd /Users/intalk/Desktop/개인/eo/be && source .venv/bin/activate && python -m pip_audit 2>/dev/null || (pip install pip-audit && python -m pip_audit)
```

## 2단계: requirements.txt 버전 확인

```bash
cd /Users/intalk/Desktop/개인/eo/be && source .venv/bin/activate && pip list --outdated --format=columns 2>/dev/null
```

## 3단계: 알려진 취약 패턴 확인

다음 패키지의 최소 안전 버전을 확인하세요:

- `cryptography` >= 42.0.0 (CVE-2024 시리즈)
- `urllib3` >= 2.0.7 (SSRF 관련)
- `pydantic` >= 2.5.0 (검증 우회)
- `sqlalchemy` >= 2.0.25 (SQL 인젝션)
- `fastapi` >= 0.109.0 (보안 패치)

## 4단계: 리포트

| 패키지 | 현재 버전 | 안전 버전 | CVE | 심각도 |
|--------|-----------|-----------|-----|--------|
| ... | ... | ... | ... | ... |

## 5단계: 자동 업데이트 제안

심각도 HIGH 이상인 패키지는 업데이트 명령어를 제시하세요:

```bash
pip install --upgrade <패키지명>
```

업데이트 후 테스트를 실행하여 호환성 확인:

```bash
cd /Users/intalk/Desktop/개인/eo/be && source .venv/bin/activate && python -m pytest -v
```
