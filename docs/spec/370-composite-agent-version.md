# 370 — 복합 에이전트 버전 (스펙 367-C: 블록 버전 freeze + 오픈 포인터)

## 왜

367 확정 모델의 심장부. 369로 블록에 불변 버전이 생겼으니, 이제 **에이전트 버전이 하위 블록
버전들을 못박아(freeze) 하나의 불변 복합 버전**이 된다. 이게 돼야:
- **캐시 키**(367-D): `agent_version_id`가 불변 → 무효화 공짜.
- **평가·배포**(367-E): 평가한 아티팩트 == 배포되는 아티팩트.
- **롤백**: v2로 되돌리면 진짜 v2 동작(밑에서 블록이 바뀌어도 불변).

현재의 갭(실측): prompt만 head 컬럼 스냅샷(`agent.prompt`+promptStale)이라는 원시적 못박기가 있고,
**model·MCP는 스냅샷조차 없이 런타임 라이브 해석** — 관리자가 MCP/모델을 고치면 오픈된 에이전트
동작이 조용히 바뀐다. C가 pins로 통일하고 promptStale 메커니즘을 은퇴시킨다.

## 확정 모델 (구남님, 2026-07-15)

- 에이전트 = **불변 단조 버전들 + 오픈 포인터 하나 + ever_opened**. draft·archived **폐기**.
- 편집 = 오픈된 버전 기준 다음 버전(오픈+1). 그 슬롯이 **미오픈 스크래치면 대체**, **오픈이력
  있으면 보호 → 새 번호**. 오픈 = 포인터 이동(롤백 = 예전 버전 오픈).
- 에이전트 버전 생성/편집 시점에 블록 버전 freeze. RAG는 제외(라이브 — 367).

## 설계

### 1. 스키마 (AgentVersion)

- `status`(draft|active|archived) **제거** → `ever_opened: bool default false` + `pins: JSONB default {}`.
- `pins` = 평평한 `{"<kind>:<name>": <version>}` 맵 (예: `{"prompt:warm-secretary": 3,
  "model:mock-llm": 1, "mcp-server:calc-tools": 2, "memory-type:장기 기억 (mem0)": 1}`).
  **config는 지금처럼 이름 참조 유지**(UI·기존 계약 최소 침습) — pins가 별도 열로 버전을 못박는다.
- 오픈 포인터 = 기존 `Agent.active_version` 재사용(의미만 "지금 오픈된 버전"으로).

### 2. 상태기계 교체 (라우트)

| 현재 | 목표 |
|---|---|
| 생성 → v1 draft | 생성 → v1 스크래치(ever_opened=false), pins=현재 head들 freeze |
| PUT 편집 → 초안 in-place 갱신 | PUT 편집 → **충돌 규칙**으로 스크래치 대체/신설 + pins **재freeze** |
| POST /versions(fork, 초안 있으면 400) | **제거** — 편집이 곧 다음 버전 작업 |
| POST /activate(draft/archived→active) | **오픈** — 포인터 이동 + `ever_opened=true` 스탬프 + head 컬럼 구체화(기존 유지). 미래 E(평가 게이트)의 관문 |
| POST /revert | **제거** — 예전 버전 activate가 곧 롤백 |
| POST /prompt/refresh (promptStale) | **은퇴** → **채택(adopt)**: pins만 head로 재freeze한 새 스크래치 생성 |

**충돌 규칙의 일반화(제 판단 — 검토 요망)**: "미오픈 스크래치는 항상 **최대 1개**" 불변식(현
단일-초안 불변식의 후계). 편집 시: 기존 스크래치가 있으면 삭제하고, 번호 = `오픈+1`(그 슬롯이
ever_opened면 `최대 오픈번호+1`)로 새 스크래치 1행을 쓴다. 구남님 규칙 두 사례가 그대로 성립:
v2 오픈+v3 스크래치→v3 대체 / v2 롤백 후 편집+v3 오픈이력→v4. 스크래치가 여럿 쌓이는 경우의
수를 원천 제거한다.

### 3. 런타임 pin 해석 (chat_context)

`_load_context`가 오픈 버전의 pins로 블록을 해석 — **369 경계 그대로**(저작 내용=pin, 운영·비밀=head 라이브):

| 블록 | pin에서(불변) | head에서(라이브) |
|---|---|---|
| prompt | body(시스템 프롬프트) | — |
| model | model_id·params·provider_id | provider의 base_url·api_key(비밀·로테이션 즉시 반영) |
| mcp-server | url·transport·tools·enabled_tools·tools_meta | auth(비밀)·published·status |
| memory-type | scope·body | — |

- 공용 헬퍼 `resolve_pinned(session, pins, kind, name) -> payload|None`(block_versions.py) —
  pin 없거나(레거시) 이력 부재면 head 폴백(정직 degrade, 로그).
- `agent.prompt` head 컬럼은 유지하되 의미 변경: "오픈 버전 pin의 body 구체화 캐시"(activate 때 pin
  payload에서 채움). promptStale 비교·PromptStaleNote·prompt/refresh는 제거.
- 노드형 노드별 모델 해석(`nodes_resolved`)도 같은 pin 경로.

### 4. "새 버전 채택" 배지 (promptStale의 후계, 전 블록으로 확장)

- 에이전트 상세: 오픈 버전 pins의 각 `버전 < 해당 블록 head.version`이면 "블록에 새 버전 —
  채택하면 새 에이전트 버전" 배지. **채택** = pins 재freeze 스크래치 생성(§2) → 오픈은 명시적.
- 블록 쪽(스펙 161 usage 화면)의 stale 계산도 pin 비교로 교체.

### 5. 삭제·개명 가드 연장

- 블록 삭제/개명 가드(093 등)는 현재 **live config 이름 참조**만 본다. 연장: **모든 AgentVersion의
  config 참조**도 검사(어느 버전이든 롤백 대상이므로) — model_registry는 이미 버전 config를 봄,
  prompt·mcp에 동일 적용.

### 6. 경계

- **source=ui만** — code(외부 commit이 버전)·external(A2A 카드)은 이 상태기계 밖(현행 유지).
- ephemeral·toolPolicy 게이트 등 기존 편집 가드(_enforce_*)는 그대로 승계.
- 오픈 시 자동 회귀(스펙 241 trigger_auto_regression)는 유지 — E의 평가 게이트가 이 자리에 선다.

### 7. 이관

- `agent_versions`: `ever_opened` 백필(= status != 'draft'), `pins` 백필(= 현재 head 버전들로
  freeze — 과거 시점 복원은 불가능하므로 현재로 고정, 정직한 최선), status 컬럼 drop.
- 마이그레이션 프로그램적 생성·트림(learning 364). 백필은 부트 멱등 함수(369 패턴 재사용).

## 깨지는 계약 (수선 목록)

- e2e api.spec: draft/fork-400/revert-400 단언 → 새 시맨틱으로 재작성.
- UI: AgentDetailPage 버전 목록(draft/active/archived 태그 → 오픈·오픈이력·스크래치 + 오픈 버튼),
  AgentForm "초안 편집" 문구, PromptStaleNote 제거, useAgents의 fork/revert 호출 제거.
- serializers: AgentOut.versions의 status 필드 → everOpened/isOpen 파생.

## 완료 조건 (수치)

- **C1 freeze 실증**: 에이전트 오픈 → 밑 블록(prompt body·mcp tools·model params) 편집 →
  **채팅 동작 불변**(sentMessages의 시스템 프롬프트=pin body·도구 목록=pin tools, SSE 실측) +
  블록 head는 새 버전. 편집 전후 응답 diff 0.
- **C2 충돌 규칙**: (a) v2 오픈+v3 스크래치 → 편집이 v3 대체(행 수 불변·내용 교체),
  (b) v3 오픈이력+v2 오픈 → 편집이 v4 신설·v3 보존(바이트 불변). HTTP 실측.
- **C3 롤백 실증**: v3 오픈 → v2 오픈(롤백) → 채팅 동작 = v2 pins(프롬프트 v2 body 실측) →
  다시 v3 오픈(롤포워드) 가능.
- **C4 채택**: 블록 새 버전 → 배지 표시 → 채택 → 새 스크래치(pins=head) 생성·오픈 전 동작 불변.
- **C5 가드 연장**: 어느 버전 config가 참조하는 블록 삭제 → 409.
- **C6 이관**: 기존 전 버전 ever_opened·pins 백필(버전 행 수 == pins 보유 행 수), status 컬럼 부재.
- **C7 무회귀**: make test SUITE_OK · make e2e green(재작성 반영) · tsc 0 · 다해상도 스샷.

## 검증 결과 (2026-07-16 — done, verify_370 ALL PASS)

- **C1 freeze 실증**: 오픈 후 프롬프트 head 편집 → 채팅 시스템 프롬프트 = pin body 불변(SSE 실측).
  MCP head에서 도구(failing_op) 제거 → **pin 에이전트는 여전히 그 도구 발동**(전용 임시 서버, 스펙 320 패턴).
- **C2 충돌 규칙**: 롤백 후 편집 → 오픈이력 v2 **바이트 불변**·v3 신설 / 재편집 → 스크래치 대체(행 수 불변).
- **C3 롤백**: v2 오픈=PIN-BODY-2 → v1 재오픈=PIN-BODY-1(예전 pin 동작 복귀, SSE 실측).
- **C4 채택**: stalePins 배지 데이터 → adopt → 스크래치 pins=head. UI 배지+버튼 브라우저 실측.
- **C6 이관**: ever_opened 백필(status!=draft)·pins 부트 백필(멱등)·status drop. 시드 에이전트 빈 pins 0.
- **C7 무회귀**: make test SUITE_OK · make e2e 39/39 · tsc 0 · 상세 화면(오픈/오픈이력/스크래치 파생
  라벨·재오픈(롤백) 버튼) 브라우저 실측.

### 실행 중 결정·발견 (기록)

- **C5 가드 연장 보류(스펙 121 존중)**: 전 버전 config 가드는 스펙 121이 "과거 버전 참조 하나가 자원을
  영구 잠금 — 과엄격"으로 **완화한 이력**(사용자 버그)과 정면 충돌. 121 유지(가드=활성 config만) +
  죽은 pin은 resolve_pinned가 None→head 폴백→기존 dangling 경고 degrade로 정직 처리. 오픈이력
  버전의 재오픈 보장은 "참조 블록이 살아있는 한"으로 경계 명시. 재논의 필요 시 구남님 판단.
- **P1 발견·봉합(스위트가 라이브 DB에서 마이그레이션 왕복)**: `verify_343_downgrade`(자체 헤더가
  virgin DB 전용 명시)를 run_suite가 라이브 DB에 직접 실행 — 369/370 이후 downgrade 왕복이 런타임
  저작 데이터(블록 이력·pins)를 지우는 **손실 왕복**이 됨(부트 백필이 head=v1로 재생성해 가려짐 —
  이력 조용히 소실). 봉합: run_one이 파일 본문의 `_throwaway_db.py` 마커를 존중해 격리 러너로 래핑
  (해당 11개 전부 virgin-DB 명시 테스트). 부수: 격리됐던 verify_059·345가 살아남(격리 해제 후보).
  스위트 후 pins 생존 실측으로 봉합 증명.
- prompt_apply(스펙 161)는 in-place 스냅샷 갱신이 불변 버전과 비정합 → **채택 스크래치 생성**으로
  재구현(반영=오픈 명시). stalePins는 단건 GET만 계산 — 상세 진입 시 refreshOne으로 로드.

## OUT

- 캐시(367-D)·평가 게이트(367-E) — 이 스펙은 불변 복합 버전까지.
- 블록 버전 선택 UI(특정 과거 버전 고르기) — 채택은 head로만(YAGNI, 367).
- code/external 에이전트의 버전 모델 — 현행 유지.
