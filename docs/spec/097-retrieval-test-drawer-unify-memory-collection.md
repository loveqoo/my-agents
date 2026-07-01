# 097 — 검색시험 드로어 통합 + 메모리 뷰 검색 UX 정합 (제안 #7)

> 상태: 초안(AI 작성, 인간 검토 대기). 제안 8항목 중 #7. 사용자 스코프 선택: **"메모리 뷰 전반 검색 UX 정합"**.
> 참고 자산: spec 072(RAG 검색시험 shared-core·drift-prevention)·spec 084(메모리 회상시험 드로어=072 미러)·
> retrospect 060/068·learning 060/087, covering-guard(learning 069/070/096 — 공유 컴포넌트=단일 레버),
> spec 030(로컬 필터=순수 프런트, 백엔드 가드와 별개), spec 053(유저 메모리 RBAC — onSearch 스코프 바인딩 보존).

## 1. 배경 / 문제 (코드 실증 — 추측 아님)

메모리 뷰의 "검색"은 **두 종류**다:
1. **의미검색(회상 시험)** — `RecallDrawer`(스펙 084). "조회 시험" 버튼 → 드로어. `memory.search` 코어로 질의.
2. **로컬 텍스트 필터** — 각 패널의 `Input placeholder="필터 (텍스트 부분일치)"`. 이미 로드된 항목을 부분일치로 거른다.

핵심 드리프트: **`RecallDrawer`(084)는 `SearchDrawer`(072, CollectionsView 내부 로컬 함수)를 손으로 미러링**한 것이다.
072의 "shared core"는 **백엔드**(`search_collections`/`memory.search`)에만 적용됐고 **UI 드로어는 각각 구현**돼 갈렸다:

| 축 | SearchDrawer(072) | RecallDrawer(084) |
|---|---|---|
| 구조 | Drawer 640 + TextArea rows2 + InputNumber(1–10) + primary 버튼 + 결과 카드 | **동일** |
| limit 라벨 | `top_k (1–10)` | `limit (1–10)` |
| 실행 버튼 | `검색` | `조회` |
| score 태그 | `유사도 {score}` | `관련도 {score}` |
| 카운트 | `결과 N건` | `회상 N건` |
| 결과 메타 | `filename`(문자열) | `scope`·`type` 태그 |
| 비활성 Alert | `!ready`(청크 없음) | `!out.enabled`(장기기억 미구성) |
| 위치 | CollectionsView.tsx 내부 로컬 함수 | 별도 파일(두 패널 공유) |

구조가 90% 같은데 두 벌로 존재 → 한쪽 개선이 다른쪽에 자동 반영 안 됨(향후 드리프트). 이것이 072가 경계한 바로 그 문제의 **UI판**이다.

## 2. 설계 결정

**결정 A — 공유 `RetrievalTestDrawer` 추출(UI covering-guard).** 두 드로어의 공통 셸(질의 TextArea + limit
InputNumber + 실행 버튼 + 결과 카드 프레임 + 스코프 전환 리셋 + 빈/에러 처리)을 한 컴포넌트로 추출. 도메인별
차이는 **props로 주입**:
- `title`, `scopeKey`(전환 시 질의·결과 리셋), `onSearch(query, limit) → { results, ... }`
- `hint`(상단 설명), `queryPlaceholder`, `limitLabel`(`top_k`/`limit`), `runLabel`(`검색`/`조회`),
  `scoreLabel`(`유사도`/`관련도`), `countLabel(n)`(`결과 N건`/`회상 N건`), `emptyMessage`
- `renderMeta(hit)` — 결과 카드 메타 렌더 프롭(컬렉션=filename, 메모리=scope/type 태그). **최대 차이라 render-prop으로.**
- `disabledAlert` — 선택적 비활성 안내(컬렉션 `!ready` / 메모리 `!enabled`). onSearch 결과의 `enabled`/상태로 판정.
- **정직성 보존(084)**: `enabled` false와 `results 빈 배열`을 구분(None≠[])하는 084의 계약을 그대로 통과시킨다.

`RecallDrawer`·`SearchDrawer`는 이 공유 컴포넌트를 감싸는 **얇은 어댑터**가 된다(각 도메인 라벨·renderMeta 주입).
→ 이후 한 곳 수정이 양쪽 반영, drift 0. 072의 백엔드 shared-core 철학을 UI로 확장.

**결정 B — 메모리 로컬 필터는 유지, 표현 정합 확인.** 두 패널(Agent/User)의 로컬 "필터" Input은 이미 동일하다.
Collections엔 로컬 필터가 없다(강제로 추가하지 않음 — 스코프 크리프 회피). 대신 메모리 패널에서 "로컬 필터"와
"조회 시험"이 **다른 것**임이 분명하도록 배치/라벨 일관 유지(필터=부분일치, 조회=의미검색). 필요 시 placeholder를
"필터 (로드된 목록 부분일치)"처럼 더 명확히.

**RBAC**: onSearch 콜백이 `searchAgentMemory(agentId,…)`/`searchUserMemory(userId,…)`로 스코프를 이미 바인딩한다.
공유 컴포넌트는 onSearch를 **불투명하게 호출만** 하므로 유저 메모리 본인-스코프(053)가 그대로 보존된다. 순수 UI
표현 변경이라 RBAC 소유권 체크리스트는 트리거되지 않는다(user_id 스코핑·`_own_scope`·`_visible_or_404` 미변경).

## 3. 구현

- `admin/src/admin/views/RetrievalTestDrawer.tsx` 신설(공유 셸). `MemorySearchOut`·`SearchHit` 양쪽을
  받도록 결과 타입을 제네릭/유니온+`renderMeta`로 흡수. 결과 항목 공통 필드=`score`·`text`.
- `RecallDrawer.tsx` → 공유 컴포넌트 어댑터로 축소(메모리 라벨·scope/type renderMeta·enabled Alert).
- `CollectionsView.tsx`의 `SearchDrawer` → 같은 어댑터로 축소(컬렉션 라벨·filename renderMeta·ready Alert).
- 메모리 패널 필터 placeholder 명확화(선택).

## 4. 완료 조건 (측정가능) — 전부 충족 ✅

- [x] **동작 동등**: 브라우저(`tests/browser/verify-drawers-097.mjs`, docs_kb ready 컬렉션 + Personal
      Secretary 에이전트)로 확인. 컬렉션=`검색 시험 · docs_kb`/`top_k (1–10)`/버튼 `검색`/질의→`결과 2건`+
      `유사도 0.037·0.007` 카드. 메모리=`회상 시험 · 에이전트 전용 기억`/`limit (1–10)`/버튼 `조회`. 도메인
      라벨이 각각 올바르게 주입됨. 스크린샷 `/tmp/097-A-collection.png`·`/tmp/097-B-memory.png` 대조 OK.
- [x] **정직성 계약 보존(084)**: 브라우저에서 메모리 질의 0건이 `alertTitle=null`(인라인 "회상된 기억이
      없습니다") = `enabled=true & 0건` 분기로 렌더 → `enabled=false`(파란 disabledAlert "장기 기억이
      비활성/미구성") 분기와 구분됨(None≠[] 유지). enabled=false 경로는 codex가 코드로 확인(어댑터가
      `out.enabled` 그대로 반환, 셸이 `!enabled`→disabledAlert).
- [x] **drift 0 구조**: 공유 셸 `RetrievalTestDrawer` 1개, 두 어댑터는 props/renderMeta만 주입(RecallDrawer 63줄,
      SearchDrawer 어댑터). 어댑터 순증가 -147줄(중복 셸 제거). 셸 정의 grep=1.
- [x] **회귀 없음**: `npx tsc --noEmit` EXIT 0(레이스 수정 후 재확인), 스코프 리셋 브라우저 확인(에이전트
      전환 후 query=""), 유저 메모리 onSearch가 `searchUserMemory(userId,…)` 바인딩 보존(코드 대조).
- [x] **적대 검증(rung③)**: codex read-only 리뷰(이 3파일 범위, ~/.claude·~/.agents·.claude/skills·agents/
      미접근). P0 없음. **P1 1건 발견**: 늦게 온 이전 스코프 검색 결과가 전환된 스코프 아래 표시되는
      stale-async 스코프 유출(원본 072/084 두 드로어에 잠재하던 결함). → 공유 셸에 request-sequence 가드
      추가(`reqSeq` ref: 스코프 전환·후속 질의 시 in-flight 무효화)로 한 번에 봉합. 정직성 계약·renderMeta
      유니온 타입·onSearch 바인딩은 통과 확인.

## 5. 알려진 잔존 / 비목표

- Collections에 로컬 텍스트 필터 추가는 **비목표**(스코프 크리프). 메모리에만 있는 채로 둔다.
- 결과 카드 시각 테마는 이미 동일(gray-2 카드) — 통합으로 자연 수렴.
