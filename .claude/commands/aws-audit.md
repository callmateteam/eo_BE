# AWS 리소스 보안 감사 스킬

AWS 인프라의 보안 상태를 종합 점검합니다.
AWS CLI가 설정되어 있어야 합니다.

## 사전 확인

```bash
aws sts get-caller-identity 2>/dev/null && echo "AWS 인증 OK" || echo "AWS CLI 미설정 - aws configure 필요"
```

## 1단계: IAM 감사

```bash
aws iam get-account-summary --output json 2>/dev/null
```

```bash
aws iam list-users --query 'Users[*].[UserName,CreateDate,PasswordLastUsed]' --output table 2>/dev/null
```

```bash
aws iam list-access-keys --query 'AccessKeyMetadata[*].[UserName,AccessKeyId,Status,CreateDate]' --output table 2>/dev/null
```

### IAM 체크리스트

- [ ] 루트 계정에 MFA 활성화
- [ ] 사용하지 않는 IAM 유저 비활성화
- [ ] 90일 이상 된 액세스 키 로테이션
- [ ] 인라인 정책 대신 관리형 정책 사용
- [ ] 역할(Role) 기반 접근 (유저 직접 권한 최소화)

## 2단계: EC2 보안 그룹

```bash
aws ec2 describe-security-groups --query 'SecurityGroups[*].[GroupId,GroupName,Description]' --output table 2>/dev/null
```

```bash
aws ec2 describe-security-groups --filters "Name=ip-permission.cidr,Values=0.0.0.0/0" --query 'SecurityGroups[*].[GroupId,GroupName]' --output table 2>/dev/null
```

### 위험 포트 확인

- 22 (SSH): 특정 IP만 허용해야 함
- 3306/5432 (DB): 프라이빗 서브넷에서만 접근
- 0.0.0.0/0 인바운드: 80/443 외에는 금지

## 3단계: RDS 보안

```bash
aws rds describe-db-instances --query 'DBInstances[*].[DBInstanceIdentifier,Engine,PubliclyAccessible,StorageEncrypted,AutoMinorVersionUpgrade]' --output table 2>/dev/null
```

### RDS 체크리스트

- [ ] PubliclyAccessible: false
- [ ] StorageEncrypted: true
- [ ] AutoMinorVersionUpgrade: true
- [ ] 백업 보존 기간 7일 이상
- [ ] 삭제 방지 활성화

## 4단계: S3 버킷 보안

```bash
aws s3api list-buckets --query 'Buckets[*].Name' --output text 2>/dev/null
```

```bash
for bucket in $(aws s3api list-buckets --query 'Buckets[*].Name' --output text 2>/dev/null); do echo "=== $bucket ===" && aws s3api get-public-access-block --bucket $bucket 2>/dev/null || echo "퍼블릭 액세스 차단 미설정!"; done
```

### S3 체크리스트

- [ ] 퍼블릭 액세스 차단 활성화
- [ ] 버전 관리 활성화
- [ ] 서버 측 암호화 (SSE-S3 또는 SSE-KMS)
- [ ] 로깅 활성화

## 5단계: CloudWatch 알람

```bash
aws cloudwatch describe-alarms --state-value ALARM --query 'MetricAlarms[*].[AlarmName,StateValue,MetricName]' --output table 2>/dev/null
```

### 필수 알람 목록

- [ ] CPU 사용률 > 80%
- [ ] 메모리 사용률 > 85%
- [ ] 디스크 사용률 > 90%
- [ ] RDS 커넥션 수 임계치
- [ ] 5xx 에러율 > 1%

## 감사 리포트

| AWS 서비스 | 상태 | 심각도 | 조치 사항 |
|-----------|------|--------|----------|
| IAM | ✅/❌ | - | |
| 보안 그룹 | ✅/❌ | - | |
| RDS | ✅/❌ | - | |
| S3 | ✅/❌ | - | |
| CloudWatch | ✅/❌ | - | |

0.0.0.0/0 인바운드 또는 PubliclyAccessible DB가 있으면 **즉시 조치**하세요.
