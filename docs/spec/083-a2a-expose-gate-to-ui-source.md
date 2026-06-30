# 083 — A2A 노출은 source=ui 에이전트에만 (원격/외부 노출 토글 제거)

## 배경 (실측)

사용자: **"등록된 원격 에이전트를 A2A로 오픈하는 것은 이상함."**

`exposed.a2a=True`는 *로컬(source=ui)* 에이전트를 우리 A2A 서버(카드+JSON-RPC)로 여는 플래그다(스펙 061).
A2A 서버는 이미 `source==ui`로 fail-closed 게이트돼 있다(`a2a_server.py:35` — non-ui면 404). 그러나
**나머지 층이 source를 안 봐서 "겉도는 죽은 상태"가 생긴다**:

| 위치 | 현재 | 문제 |
|---|---|---|
| `agents.py:289` `expose_agent` | source 무관하게 `exposed={"a2a": body.a2a}` 저장 | code/external에 True 박혀도 서버는 404 → dead state |
| `AgentsView.tsx` CodeAgentDetail(`:645`)·ExternalAgentDetail(`:881`) 드로어 | 둘 다 `<ExposeSwitch label="A2A로 공개"/>` 무조건 렌더 | 원격 에이전트에 노출 토글 제시 = "이상함"의 실체 |
| `AgentsView.tsx` 테이블 "공개" 컬럼(`:1463`) | 모든 행에 Switch | non-ui도 토글 보임 |
| `seed.py:260` | code 에이전트("Doc Translator")에 `exposed={"a2a": True}` | 시드 자체가 불일치(서버는 404) |

`agents.py:404`엔 이미 *"우리가 소비측(클라이언트) — 서버측 노출과 무관"* 주석이 있는데도 `/expose`와 UI는
플립을 허용해 왔다. external 에이전트는 *이미 자기 A2A 카드를 가진* 외부 에이전트라 우리 A2A로 재노출은
proxy-of-proxy, code 에이전트는 원격 프록시라 마찬가지로 무의미하다.

## 목표 (완료 조건 — 측정 가능)

1. **불변식**: `exposed.a2a == True` ⟹ `source == "ui"`. 모든 입구(API·시드·기존 데이터)에서 성립.
2. **백엔드 권위**: `PUT /expose`가 `body.a2a==True`이고 `source != "ui"`면 **400 거부**(프런트 숨김에
   의존 금지 — learning 027). `body.a2a==False`는 source 무관 항상 허용(stale 끄기 가능).
3. **UI**: code/external 드로어와 테이블 "공개" 컬럼에서 노출 토글을 **source=ui일 때만** 노출. 원격
   에이전트엔 토글 자체가 안 보인다(테이블은 `—` 표시).
4. **기존 데이터·시드 정합**: 마이그레이션으로 `source != 'ui'`의 stale `exposed.a2a=true`를 false로
   내리고, `seed.py:260`을 `{"a2a": False}`로 고친다.

## 설계

### 백엔드 — `agents.py::expose_agent`
```python
agent = await _load_agent(session, agent_id)
if agent is None:
    raise HTTPException(status_code=404, detail="agent not found")
if body.a2a and agent.source != "ui":
    # 원격(code)·외부(external)는 이미 원격 A2A/프록시 — 우리 A2A로 재노출은 proxy-of-proxy(스펙 083).
    # A2A 서버(a2a_server.py:35)도 non-ui면 404라 노출해도 dead state. 입구에서 거부.
    raise HTTPException(status_code=400, detail="원격/외부 에이전트는 A2A로 노출할 수 없습니다 (source=ui만 노출 가능)")
# JSONB 통째 교체는 형제 키 파괴(적대 codex P1) — merge 후 재대입으로 a2a만 갱신.
agent.exposed = {**(agent.exposed or {}), "a2a": body.a2a}
```
- **`body.a2a==False`는 항상 통과** — stale 플래그를 끄는 경로를 막지 않는다(멱등 clear).
- a2a_server 게이트와 *같은 술어*(`source != "ui"`)로 일관 — 입구·서비스 두 층 정렬.

### 마이그레이션 — `a3b4c5d6e7f8_expose_gate_ui_only_spec_083.py` (down=`f2a3b4c5d6e7`)
```sql
UPDATE agents
SET exposed = jsonb_set(COALESCE(exposed, '{}'::jsonb), '{a2a}', 'false'::jsonb, true)
WHERE source <> 'ui' AND (exposed ->> 'a2a') = 'true';
```
- 멱등(이미 false면 매치 안 함). `jsonb_set`은 a2a 키만 끄고 형제 키 보존(통째 교체는 적대 codex P1).
  downgrade는 no-op(과거 잘못된 상태 복원 안 함 — 의미 없음).

### 시드 — `seed.py:260`
`exposed={"a2a": True}` → `exposed={"a2a": False}` (code 에이전트). external 시드(`:297`)는 이미 False.

### 프런트 — `AgentsView.tsx`
- **CodeAgentDetail**(`:644-652`)·**ExternalAgentDetail**(`:880-888`): `ExposeSwitch` 블록 **제거**
  (이 두 컴포넌트는 source 전용이라 조건 불필요 — 통째 삭제). `onToggleExpose` prop도 두 컴포넌트에선
  미사용 처리.
- **ui 드로어**(`:1094-1102`): 그대로 유지(source=ui).
- **테이블 "공개" 컬럼**(`:1457-1469`): `a.source === 'ui'`일 때만 Switch, 아니면 `—`(흐린 텍스트).
- 배지(OverviewView·DebugChat): 불변식상 `exposed.a2a=true ⟹ ui`라 무변경으로도 정직해지나, **명시
  방어로** 노출 카운트/배지도 `source === 'ui' && exposed.a2a`로 좁혀 self-documenting하게 한다(저비용).

## RBAC 체크리스트 적용 여부
**미적용** — 노출은 *source 기반 capability 게이트*(이미 서버 강제)이지 user_id·테넌트·소유권 축이 아니다.
새 소유 경계·열거 오라클 없음. 트리거(객관 신호: user_id/테넌트 컬럼·`_own_scope`/`_visible_or_404`/
`_assert_*owns`) 해당 없음.

## 검증 사다리 (비겹침)
1. **단위/라이브**: `expose_agent`에 (ui+true)→200·(code+true)→400·(external+true)→400·(code+false)→200(clear)
   네 케이스. 마이그레이션 적용 후 code/external의 stale true가 false로 내려가고 ui의 true는 보존(불변식 단언).
2. **브라우저**: code/external 드로어에 노출 토글 *없음*(부정 단언)·ui 드로어엔 *있음*·테이블 non-ui 행 `—`·
   ui 행 Switch. (verify-ui-browser, 양성+음성)
3. **적대 codex**: 데이터 마이그레이션(JSONB UPDATE)이 정상 ui 노출을 끄지 않나·400 거부가 clear 경로를
   막지 않나·불변식 우회 입구(register/connect/create가 non-ui+true 만들 수 있나) "보장 목록의 여집합".

## 검증 결과 (3런)
- **rung1 단위/라이브** (`tests/verify_083_expose_gate.py`, 실DB) — **12/12 PASS (VERIFY083_OK)**:
  G1 ui+true→200·G2 code+true→400(+거부 후 무변동)·G3 external+true→400·G4 code+false→200(clear)·
  **G5 ui+형제키 expose→a2a만 갱신·note 보존**. M1 code stale→false 청소·M2 ui true 보존·M3 불변식
  위반행=0·**M4 jsonb_set이 a2a만 끄고 형제키 note 보존**. 라이브 마이그레이션 적용 후 위반행 0.
- **rung2 브라우저** (`tests/browser/shot-expose-gate-083.mjs`, 시스템 Chrome) — **EXPOSE_GATE_083_OK**:
  테이블 Doc Translator(code) 행 `—`(노출불가)·ui 드로어(Research Assistant) 토글 *있음*·
  code 드로어(Doc Translator) 토글 *없음*. 3캡처 육안 확인. tsc 0에러.
- **rung3 적대 codex** — 불변식 우회 입구 0·alembic 단일 head 확인. **P1 2건**(`expose_agent`·마이그레이션이
  JSONB 통째 교체 → 형제 키 파괴) → merge / `jsonb_set`으로 하드닝(G5·M4로 회귀 잠금). **P2**: mock code
  에이전트 `a2a:true`→false·`toggleExpose` 중앙 source 가드 추가·테스트 형제키 보존 단언 추가. 모두 반영.

## 완료 체크
- [x] `expose_agent` non-ui+true → 400, false·ui는 통과 (형제 키 보존 merge)
- [x] 마이그레이션으로 stale 정리(불변식 성립, jsonb_set 형제키 보존), seed 수정
- [x] UI: code/external 토글 제거·테이블 non-ui `—`·ui 유지, 배지 source 좁힘, toggleExpose 가드
- [x] 단위/라이브(12) + 브라우저(양성·음성) + 적대 codex 그린, 무회귀
