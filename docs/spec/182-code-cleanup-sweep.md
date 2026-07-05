# 182 — 코드 정리 훑기(죽은 코드·오너십 통합·중복·재발방지)

## 배경
"코드 정리를 좀" 요청 → deep-reasoner 2개(프론트/백엔드) + 기계 스캔(tsc noUnusedLocals·pyflakes)으로
전체 훑기. 소스는 전반적으로 깨끗(미사용 import ~4, 죽은 코드 소수). 확정 후보만 정리한다. 사용자
결정: **전부 적용(오너십 통합 포함)**.

## 후보(검증된 것만 — 참조 0 확인)

### P1. 죽은 코드 삭제(safe, 참조 0)
**프론트 `admin/src/`**
- `api.ts`: 미사용 export 함수 8개 — `getAgent`·`listAgentImpls`·`listBatchJobs`·`testSavedModel`·
  `updateModel`·`listUserIds`(스펙 032가 제거했다 적었으나 잔존)·`listAgentMemory`·`listUserMemory`
  + 이들만 쓰던 `interface AgentMemory`.
- `shared.tsx`: 죽은 컴포넌트 `DemoBanner`.
- `AgentsView.tsx`: 미사용 import `useRef`·`Checkbox`.

**백엔드 `packages/api/src/api/`**
- `catalog.py:stats`·`eval_harness.py:EvalReport.failures`·`ownership.py:owner_scope_filter`(라우터가
  직접 스코핑) — 삭제 + ownership 모듈 docstring 언급 제거.

> **실행 정정(적용 직전 재-grep)**: deep-reasoner가 "죽음"이라던 3건이 실제로는 **테스트가 사용** —
> `memory/backend.py:_reset_cache`(verify_040)·`net_guard.py:_set_allowed_hosts_for_test`(verify_060/063)·
> `ownership.py:may_use`(verify_112 단위). **삭제 취소·보존**. 에이전트의 "tests 포함 참조 0" 주장은
> 신뢰 못 함 → 삭제 직전 개별 재확인이 필수(회고 163).

### P2. 오너십 단일 규칙 복원(통합)
`ownership.next_owner`(죽음)와 `chat._next_owner`(사용 중)가 소유권-무덮어쓰기를 **각자 구현**. 경계
차이: `current==""`(빈 문자열)에서 `next_owner`는 새 값 부여(미소유 취급), `_next_owner`는 보존(이전
거부, fail-closed). **보안상 안전한 `_next_owner` 로직을 정본으로** — `ownership.next_owner`를 그
의미로 정정하고, `chat.py`가 import해 쓰게 하고 `_next_owner` 삭제. 경계 단위 테스트로 봉인.

### P3. 중복 JSX 추출
`ApprovalsView`의 `ApprovalCard`/`HistoryCard`가 카드 헤더·권한/액션 태그 JSX를 복붙. `CardHeader`·
`PermActionTags` 소컴포넌트로 추출. 승인 화면 시각 회귀 캡처로 검증.

### P4. 재발 방지 장치
tsconfig `noUnusedLocals`+`noUnusedParameters` 켜기 → 미사용 import/지역을 tsc가 자동 차단(같은
실수 장치화). 켠 뒤 tsc 클린 확인(P1에서 미사용 2건 제거했으므로).

## RBAC 경계(P2가 인가 코드 — 체크리스트)
- P2는 소유권 판정 헬퍼 통합. **의미 무회귀가 핵심** — `_next_owner`의 정확한 진리표(빈값 보존·None
  부여·타인 보존·동일 부여)를 그대로 옮기고 단위 테스트로 고정. 인가 경계 완화 아님(오히려 dead였던
  `next_owner`의 `""` 미소유 취급이라는 잠재 구멍을 fail-closed로 봉합).

## 검증(완료 조건)
- **기계**: tsc(noUnusedLocals 켠 채) exit 0, pyflakes 미사용 0(재실행), 백엔드 import 무오류.
- **P2 단위**: next_owner 진리표 테스트(빈값·None·타인·동일·`""`) + chat resume 소유권 무회귀(기존
  verify_066/068 계열 통과).
- **P3 시각(타자)**: 승인 화면 대기/처리됨 탭 캡처 — 정리 전후 시각 동일(회귀 0).
- **삭제 안전**: 각 삭제 대상 재-grep으로 참조 0 재확인(적용 직전).

## 단계
- P1 삭제 → P4 tsconfig+tsc → P2 오너십 통합+테스트 → P3 중복 추출+시각검증 → 종합 검증.
