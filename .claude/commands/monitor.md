# 서버 모니터링 및 로그 분석 스킬

서버 상태를 모니터링하고 로그를 분석합니다.

## 1단계: 애플리케이션 상태
```bash
curl -s http://localhost:8000/health 2>/dev/null || echo "서버가 실행 중이지 않습니다"
```

## 2단계: 프로세스 확인
```bash
ps aux | grep -E "uvicorn|gunicorn|python.*main" | grep -v grep
```
```bash
lsof -i :8000 2>/dev/null || echo "포트 8000 사용 프로세스 없음"
```

## 3단계: 리소스 사용량
```bash
top -l 1 -s 0 | head -12 2>/dev/null || top -bn1 | head -12 2>/dev/null
```
```bash
df -h / 2>/dev/null
```

## 4단계: 로그 분석
```bash
cd /Users/intalk/Desktop/개인/eo/be && find . -name "*.log" -type f 2>/dev/null | head -10
```

로그 파일이 있으면:
- ERROR/CRITICAL 레벨 로그 식별
- 최근 1시간 내 에러 패턴 분석
- 반복되는 에러가 있으면 원인 추적

## 5단계: AWS 서비스 상태 (AWS CLI 설치 시)
```bash
aws sts get-caller-identity 2>/dev/null && echo "AWS 인증 OK" || echo "AWS CLI 미설정"
```
```bash
aws ec2 describe-instances --query 'Reservations[*].Instances[*].[InstanceId,State.Name,InstanceType]' --output table 2>/dev/null || echo "EC2 조회 불가"
```
```bash
aws rds describe-db-instances --query 'DBInstances[*].[DBInstanceIdentifier,DBInstanceStatus,Engine]' --output table 2>/dev/null || echo "RDS 조회 불가"
```

## 6단계: 모니터링 리포트

### 서버 상태
| 항목 | 상태 | 값 |
|------|------|-----|
| 애플리케이션 | 🟢/🔴 | |
| CPU 사용률 | 🟢/🟡/🔴 | N% |
| 메모리 사용률 | 🟢/🟡/🔴 | N% |
| 디스크 사용률 | 🟢/🟡/🔴 | N% |
| AWS 서비스 | 🟢/🔴 | |

### 주의 필요 사항
- CPU 80% 이상: 🔴 스케일링 필요
- 메모리 85% 이상: 🔴 메모리 누수 가능성
- 디스크 90% 이상: 🔴 로그 정리 필요
- 에러 로그 급증: 🔴 즉시 조사 필요
