# 296 — 요약 칩 브로커 MCP 집계(320 P3) + "stale verifier"의 진짜 정체 (스펙 321)

## 무엇을 했나

두 갈래 위생 작업으로 시작 — (1) 320 P3(요약 칩이 브로커 MCP 실패 미집계), (2) stale verifier 정리.
(2)를 파헤치니 전제가 무너져 재스코프했고, 그 과정에서 더 큰 교훈이 나왔다.

## 핵심 배운 것

### 1) 측정 방법이 측정 대상을 오염시킨다 — 공유 DB 전수 sweep의 함정
"어떤 verifier가 stale인가"를 재려고 159개 `verify_*.py`를 **공유 라이브 DB에 순차 실행**했더니 35 실패.
그런데 격리 재실행하니 대부분 stale이 **아니었다**:
- **DB 상태 오염·순서 의존**: verify_101은 sweep 직전 단독 통과했는데 sweep 뒤 실패 — 앞선 테스트가
  시드를 바꿔서. **sweep 자체가 159개를 돌려 DB를 변이**시켰다(고아행·승인정책 드롭 등). 측정 행위가
  측정 대상을 망가뜨린 것.
- **cwd 의존**(115: 상대경로 `src/agent/...`), **전제조건 게이트**(137·140·141·142·143: Obsidian·실모델
  부재=예상 skip), **fresh-seed 가정**(059: mock 기본 모델 — 사용자가 실모델 추가한 dev DB선 원래 안 됨).
→ **전수 sweep은 "stale 측정" 도구로 부적합.** 진짜 stale은 격리+진단으로만 갈린다(302 교훈의 연장:
"낡았겠지 단정 금지"를 측정 방법 선택에까지 적용).

### 2) raw verify 스크립트 ≠ 유지되는 회귀 스위트
159개 `verify_*.py`는 각 스펙 **개발기의 일회성 검증 스크립트**다. 함께/공유 DB에 돌리도록 격리 하네스가
없다. 실제 회귀 스위트는 `make suite`(큐레이션된 51/51). "verify 일괄 정리"는 개별 fake 몇 개 고치기가
아니라 **스위트 격리/큐레이션**이라는 큰 별도 작업 → 재스코프해서 확실한 것만(P3·verify_125·고아 정리)
처리하고 나머지는 백로그.

### 3) 전제가 무너지면 재스코프를 먼저 — 무리한 완주 금지
사용자가 "stale verifier 정리"를 작은 청소로 골랐는데 실측이 대형 문제로 드러났다. 35개를 다 건드리는
대신 **진단→보고→재스코프 승인**을 거쳐 경계 명확한 3건만. 삽을 더 파기 전에 사용자와 합의(빠른 합의
규칙: 단정 전에 한 겹 더 + 사용자에 정직 보고).

### 4) 부수 발견은 원인까지 규명해야 — 테스트 변이 vs 프로덕션 버그
`local-tools.delete_record`의 승인정책(HIL 게이트, 스펙 041)이 드롭돼 있었다(안전 관련!). "rediscover가
merge-preserve 실패했나?"(스펙 177 회귀 의심) → **직접 rediscover 테스트로 확인하니 승인정책 정상 보존**.
즉 프로덕션 버그가 아니라 **sweep의 어떤 테스트가 공유 local-tools를 편집해 드롭**한 것(테스트 변이).
복원 + 프로덕션 무결 확인. **드롭을 발견하고 곧장 "rediscover 버그"로 단정했으면 오진**이었다 — 실제
경로를 재현해 원인을 갈랐다.

### 5) 320 P3 = 형제 칩 대칭
요약 칩의 rag는 직접(`trace.mcp` server='rag')+브로커(`brokerCalls` rag:*)를 합산하는데 mcp는 직접만
셌다. 320이 브로커 MCP 실패를 `brokerCalls[].error`로 표면화한 뒤에도 칩이 어긋남(인스펙터 카드는 정합,
상단 칩만). rag 패턴을 mcp에 미러(`startsWith('mcp:')`로 memory:·agent: 배제). 검증=검증된 rag 경로의
대칭 복제라 tsc/build+논리 동일로 비례.

## 검증
- P3: tsc/build 클린 + rag 집계 대칭 미러. verify_125: 18/18. 고아행: 0. delete_record 승인 복원.
- 브로커 코어 무결(verify_100/294 통과)·rediscover 승인 보존 확인(스펙 177 무결).

## 잔여(백로그)
- **verify 스위트 격리 하네스**(대형): fresh-DB-per-run 또는 curation. 159개 raw 스크립트가 공유 DB·cwd·
  전제조건에 얽혀 함께 못 돌린다. sweep가 dev DB를 변이시켰으니(승인 복원 외에도 059/083/101 등 fresh-seed
  가정 실패 잔존), verifier 스위트 작업 시 **reseed 기준선**이 전제(단 dev 도그푸딩 데이터 소실=사용자 결정).
- 029(`agents.py`→`agents/` 분할)·127(`infer` kwarg)·158(threshold 기본값) 등 개별 stale 후보 미처리.

관련: [[whole-fix-over-minimal-patch]] · [[probe-deeper-before-concluding]] · [[context-optimization-is-scaffolding]] · 스펙 302(stale verifier — "낡았겠지 방치가 실 회귀 은폐")
