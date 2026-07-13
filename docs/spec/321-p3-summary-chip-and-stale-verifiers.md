# 321 — 요약 칩 브로커 MCP 집계(320 P3) + stale verifier 정리

## 배경 / 동기

두 갈래 위생 작업(사용자 선택 2026-07-13):

1. **320 P3** — 메시지 요약 칩의 "mcp 실패" 카운트가 **브로커 MCP 호출을 안 센다.** `DebugChat.tsx:939-940`은
   `mcpOk`/`mcpFail`을 `trace.mcp`(직접 경로)에서만 집계한다. 바로 위 rag 칩(`:935-938`)은 직접(`mcp
   server='rag'`)+브로커(`brokerCalls` `rag:*`)를 **합산**하는데 mcp만 비대칭. 스펙 320이 브로커 MCP 실패
   사유를 `brokerCalls[].error`로 표면화했으니, 이제 그 실패가 요약 칩에도 세져야 정합(인스펙터 카드는
   이미 표시 — 상단 칩만 어긋남).

2. **stale verifier 정리** — 실 시그니처에서 드리프트한 낡은 테스트 fake 수선. **단, 302 교훈**("실패
   verifier '낡았겠지' 방치가 실 회귀 은폐" — 190은 stale 아닌 실 프로덕션 회귀였음)대로, **각 실패를
   낡음으로 단정하지 않고 진단**한다. 사전 측정 결과 백로그가 나열한 100/103/130/131은 이미 302에서
   초록(현재 통과), 실제로 실패하는 건 아래.

## 측정된 현재 실패 + 진단 (2026-07-13, 서버·DB 라이브)

전수 sweep(159개, 서브에이전트) → 35 실패. **격리 재실행으로 진단하니 대부분 stale이 아님**:

- **DB 상태 오염/순서 의존**(101·083·059 등) — 깨끗한 시드에선 통과. verify_101은 320 회귀 때 단독 통과
  했으나 sweep가 시드를 바꾼 뒤 실패. **sweep 자체가 159개를 공유 DB에 돌려 오염**을 만들고 크래시
  고아행까지 남김(`_verify093_*`·`_verify122_*`).
- **cwd 의존**(115: 상대경로 `src/agent/...`로 cwd=packages/agent 기대) — sweep cwd에서 거짓 실패.
- **전제조건 게이트**(137·140·141·142·143: Obsidian·실모델 필요) — 예상된 skip(실패 아님).
- **진짜 stale**: 소스 드리프트(029: `agents.py`→`agents/` 패키지 분할), fake 드리프트(**125 threshold**
  확정·127 `infer` kwarg·158 threshold 기본값).

**핵심 인식**: `make suite`(회고들의 51/51)는 **큐레이션된 부분집합**. 159개 raw `verify_*.py`는 각 스펙
개발기의 일회성 검증 스크립트라 함께/공유 DB 실행용으로 유지된 게 아님 → "일괄 정리"는 사실 **verify
스위트 격리/큐레이션**이라는 큰 별도 작업(백로그).

## 재스코프 (사용자 승인 2026-07-13)

무리해서 35개를 다 건드리지 않고 **확실히 실재하고 경계 명확한 것만**:
1. **320 P3** — 요약 칩 브로커 MCP 집계(작음·확실).
2. **verify_125 threshold fake** — 084가 이미 `**_kw`로 봉합한 것과 동일 드리프트(작음·확실).
3. **정리** — sweep가 남긴 고아 테스트 행 삭제 + 백로그에 "verify 스위트 격리 하네스"를 별도 대형 항목 기록.
029·127·158 등 나머지 stale 후보는 개별 확인 필요·일부 소스 분할 추종 → 백로그로.

## 설계 / 실행

### 1) 320 P3 — 요약 칩 브로커 MCP 집계 (rag 패턴 미러)

`DebugChat.tsx` mcpOk/mcpFail에 브로커 `mcp:*` 호출을 rag와 동형으로 합산:
```ts
const mcpOk = trace.mcp.filter((c) => c.server !== 'rag' && c.status !== 'error').length +
  (trace.brokerCalls?.filter((b) => b.cap_id.startsWith('mcp:') && !b.error).length ?? 0)
const mcpFail = trace.mcp.filter((c) => c.server !== 'rag' && c.status === 'error').length +
  (trace.brokerCalls?.filter((b) => b.cap_id.startsWith('mcp:') && b.error).length ?? 0)
```
`memory:`·`agent:` cap은 mcp 칩 대상 아님(startsWith('mcp:')로 정확 배제). 성공만 mcp/실패만 mcp 실패(기존
"성공만 센다" 원리 보존).

### 2) stale verifier — 전수 sweep 후 각 실패 진단·수선

- 159개 `tests/verify_*.py` 전수 실행(서브에이전트 측정)으로 **현재 실패 전부** 확정.
- 각 실패를 **stale fake(시그니처/명명/컬렉션 드리프트) vs 실 회귀**로 판정(302 교훈). stale면 fake를 실
  시그니처에 맞춤(예: verify_125 `search`에 `**_kw`/`threshold=None`), 실 회귀면 별도 보고 후 프로덕션 수선.
- 낡음 단정 금지 — 판정 근거를 회고에 기록.

## 범위 밖 (OUT)

- 요약 칩에 agent 위임 실패 카운트 신설(별도 어포던스 — 현재 mcp/rag 칩만).
- verify 하네스 구조 개편(개별 수선만).
- 통과 중인 verifier 손대기(무회귀).

## 검증

- **320 P3**: 브라우저 rung — 브로커 MCP 실패 유발(전용 서버+failing_op를 조율형 위임으로) → 요약 칩에
  "mcp 실패 1" 표시 단언. 또는 최소 tsc/build + 320 브라우저 재현에 칩 집계 확인.
- **stale verifier**: 수선한 verifier 각각 재실행 초록 + 손대지 않은 것 무회귀(전수 재-sweep 차등).
- lint/type/tsc/build 클린.

## 완료 조건

- 요약 칩이 브로커 MCP 성공·실패를 rag와 대칭으로 집계(인스펙터 카드와 정합).
- 측정된 stale verifier 전부 초록, 각 판정(stale/실회귀) 근거 회고 기록.
- 통과 verifier 무회귀. metrics-fast 클린.

## 결과 (2026-07-13)

- **320 P3**: `DebugChat.tsx` mcp 칩을 rag와 동형으로 브로커 `mcp:*` 합산. tsc/build 클린. 검증=검증된
  rag 집계의 대칭 미러(논리 동일).
- **verify_125**: `_FakeBackend.search`에 `**_kw` 추가(084 선례) → 18/18.
- **정리**: `_verify*` 고아행(에이전트·mcp·모델·프로바이더·**API에 안 보이는 고아 컬렉션**까지) 전량 삭제 → 0.
- **부수 발견/수정**: `local-tools`의 `delete_record` 승인정책(HIL 게이트, 스펙 041)이 sweep 테스트의 공유
  상태 변이로 드롭돼 있었음 → 복원. **rediscover는 승인정책을 정상 보존**(직접 테스트로 확인 — 스펙 177
  merge-preserve 무결, 프로덕션 버그 아님). 브로커 코어 정상(verify_100/294 통과).
- **큰 발견(백로그)**: "stale verifier 일괄 정리"는 사실 **verify 스위트 격리 문제**. 159개 raw
  `verify_*.py`를 공유 라이브 DB에 순차 실행하면 (a)상태 오염·순서 의존 (b)cwd 의존 (c)전제조건 게이트
  (d)fresh-seed 가정으로 대량 거짓 실패가 나고, **sweep 자체가 DB를 변이**시킨다(측정이 측정 대상을
  오염). `make suite`(큐레이션 51/51)만이 유지되는 회귀 스위트. → 별도 대형 항목.
