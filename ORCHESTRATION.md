# EO Backend - 오케스트레이션 워크플로우

> AgentSys + RIPER 패턴 기반 워크플로우 파이프라인
> 모든 작업은 페이즈 게이트를 통과해야 다음 단계로 진행됩니다.

---

## 핵심 원칙

1. **페이즈 게이트**: 각 단계의 통과 조건을 충족해야 다음 단계 진행
2. **자동 체이닝**: 에이전트 간 작업이 자동으로 연결됨
3. **확실성 기반 판단**: HIGH는 자동, MEDIUM은 확인 후, LOW는 제안만
4. **토큰 효율**: 정규식/AST로 먼저 탐지 → LLM은 판단에만 사용

---

## 워크플로우 1: 기능 개발 파이프라인 (/project:ship)

### Phase 1 - Research (조사)

- **에이전트**: 없음 (사용자 또는 자동)
- **작업**: 요구사항 분석, 기존 코드 탐색
- **게이트**: 요구사항이 명확한가?

```
→ 불명확: 사용자에게 질문
→ 명확: Phase 2로 진행
```

### Phase 2 - Plan (계획)

- **에이전트**: implementation-agent
- **작업**: 구현 계획 수립, 영향 범위 파악
- **산출물**: 변경할 파일 목록, 접근 방식
- **게이트**: 사용자 승인

```
→ 승인: Phase 3로 진행
→ 수정: 계획 재수립
```

### Phase 3 - Implement (구현)

- **에이전트**: implementation-agent + db-agent
- **작업**: 코드 작성, 모델/스키마/서비스/API
- **게이트**: 코드 실행 가능 (구문 오류 없음)

```
→ 오류: 즉시 수정
→ 성공: Phase 4로 진행
```

### Phase 4 - Verify (검증)

- **에이전트**: qa-agent → security-agent → perf-agent
- **병렬 실행**:

```
[qa-agent]       린트 + 테스트 + 커버리지
[security-agent] 보안 스캔 + 시크릿 탐지
[perf-agent]     N+1 쿼리 + async 검증 (필요 시)
```

- **게이트**: 모든 검증 통과

```
→ 실패: 이슈 수정 후 Phase 4 재실행
→ 통과: Phase 5로 진행
```

### Phase 5 - Review (리뷰)

- **에이전트**: review-agent
- **작업**: 종합 코드 리뷰 (5개 관점)
- **게이트**: 승인 또는 수정필요

```
→ 승인: 완료
→ 수정필요: Phase 3로 돌아감
→ 반려: Phase 2로 돌아감
```

---

## 워크플로우 2: 배포 파이프라인 (/project:deploy-check)

```
Phase 1: 코드 상태 확인
    ├─ 커밋되지 않은 변경 있음 → 중단
    └─ 클린 → Phase 2

Phase 2: QA 게이트
    ├─ 테스트 실패 → 중단
    ├─ 린트 오류 → 자동 수정 후 재시도
    └─ 통과 → Phase 3

Phase 3: 보안 게이트
    ├─ HIGH 이슈 → 배포 차단
    ├─ MEDIUM 이슈 → 경고 후 사용자 판단
    └─ 통과 → Phase 4

Phase 4: 인프라 확인
    ├─ 환경변수 누락 → 중단
    ├─ Docker 빌드 실패 → 중단
    └─ 통과 → Phase 5

Phase 5: 최종 승인
    └─ 사용자 확인 → 배포 진행
```

---

## 워크플로우 3: 자동 태스크 (/project:next-task)

AgentSys의 next-task 패턴을 적용합니다:

```
1. MEMORY.md에서 기술 부채 / 알려진 이슈 확인
2. git log에서 TODO, FIXME, HACK 코멘트 탐색
3. 테스트 커버리지 낮은 모듈 식별
4. 우선순위 매기기 (보안 > 버그 > 기능 > 개선)
5. 최우선 태스크 제안
6. 사용자 승인 → 기능 개발 파이프라인 자동 시작
```

---

## 워크플로우 4: 보안 감사 (/project:security)

Trail of Bits 보안 스킬 패턴:

```
Phase 1: 정적 분석 (빠름, 토큰 비용 없음)
    ├─ bandit -r app/
    ├─ grep 시크릿 패턴 (AKIA, password=, token=)
    └─ .gitignore 검증

Phase 2: 코드 감사 (LLM 판단)
    ├─ SQL 인젝션 가능성
    ├─ 인증/인가 누락
    ├─ 입력 검증 누락
    └─ CORS / JWT 설정 검증

Phase 3: 인프라 감사
    ├─ AWS IAM 정책
    ├─ 보안 그룹 (0.0.0.0/0 체크)
    ├─ S3 퍼블릭 액세스
    └─ SSL/TLS 설정

Phase 4: 리포트 생성
    └─ 심각도별 테이블 + 수정 가이드
```

---

## 에이전트 호출 맵

어떤 상황에서 어떤 에이전트가 활성화되는지 빠른 참조:

```
"새 API 만들어줘"        → implementation-agent → qa-agent → review-agent
"보안 점검해줘"          → security-agent
"테스트 돌려줘"          → qa-agent
"배포해도 되나?"         → qa-agent → security-agent → infra-agent
"느린 것 같아"           → perf-agent
"DB 스키마 바꿔야 해"    → db-agent → qa-agent
"이 코드 리뷰해줘"      → review-agent
"다음 할 일 뭐야?"      → MEMORY.md 참조 → 태스크 제안
```
