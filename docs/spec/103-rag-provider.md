# 103 — 능력 브로커 Phase 2: RAG provider(kind=rag)

- 선행: 100(브로커·정책 게이트·A2A provider), 101(provider 시임 + MCP provider + 서브스텝 HIL),
  102(전략 교체형 오케스트레이션), 037/072(RAG retrieval 공유 코어 `search_collections`)
- 관련 학습: 100(untrusted 데이터 채널), 101(provider 시임으로 kind 추가), 102(둘째/셋째 구현이 추상 측정),
  072(retrieval 단일 코어 — 평행 구현 금지)

## 배경 / 왜

능력 브로커는 오케스트레이터가 **필요할 때 능력을 발견·호출**하는 단일 시임(discover/describe/invoke)이다.
지금 번호부에 등록된 kind는 둘 — `agent`(A2A)·`mcp`(툴 단위). Phase 2의 첫 조각으로 **`rag`(문서 컬렉션
검색)** 를 셋째 provider로 추가한다.

**왜 RAG를 먼저(3안 중 최우선)**:
- **읽기 전용** — 승인 게이트(HIL)가 필요한 부수효과가 없다. `approval_for`가 항상 None → 위험 표면 최소.
- **주인 없는 공유 카탈로그** — `Collection`은 owner/user_id가 없다(Agent·McpServer와 동일). 그래서 현재
  인가 경계(allowlist ∩ kind-RBAC)에 **재작업 0**으로 얹힌다. per-user 인가는 memory provider가 강제하는
  후속 과제(3안 = 인가 입도)로 분리된다.
- **셋째 구현이 시임을 측정** — provider 시임이 새지 않는다는 건 101(둘째 구현 MCP)까지 *주장*이다.
  성격이 또 다른 셋째(read-only·DB backing·공유 코어 재사용)가 `_CapabilityProvider` 계약만으로
  깔끔히 붙으면 추상 경계가 재실증된다(039/085/102 재적용).
- **코어는 이미 있다** — `runtime.search_collections`가 인-챗 RAG 도구와 retrieval 시험(072)이 공유하는
  단일 코어. provider는 이 코어를 **재사용**(평행 구현 금지 = drift 0, 072의 규율 연장).

## 목표

1. `RagProvider`(kind=`rag`)를 `_CapabilityProvider` 계약으로 구현하고 `PolicyScopedBroker._providers`에 등록.
2. cap_id 네임스페이스 `rag:<collection_name>`. `_kind_of`/파서를 rag 접두사까지 확장(정책·라우팅 무변경 원칙).
3. 발견·describe·invoke가 **기존 정책 게이트(allowlist ∩ RBAC·deny-by-default·존재 비노출·단일 `_permitted`)**
   를 그대로 상속. RagProvider는 정책을 **모른다**(브로커가 provider 호출 전에 게이트 — 게이트 단일 지점).
4. invoke는 `search_collections` 코어를 재사용해 상위 청크를 텍스트로 접어 반환. 결과 trust=**untrusted**
   (문서 내용 = 데이터, 지시 아님 — learning 100 채널 격리를 synthesize가 이미 강제).
5. 검증 3런(단위·통합·적대) + 셋째-provider 시임 무누수 측정.

## 비목표 (명시 경계)

- **per-cap·per-user 인가 + 소유권**: `Collection`도 owner 없는 공유 카탈로그다. 경계는 여전히
  `(에이전트 config allowlist) ∩ (유저 kind-RBAC `capability:rag`)`. member가 rag를 쓰려면 정책 부여가
  필요(기본 시드는 admin `('*','*')`만 → deny-by-default). codex 100/101 [P1] #1/#2의 연장 — 3안(인가 입도)
  으로 분리(memory provider가 이를 강제).
- **memory provider(kind=memory)**: per-user 데이터라 인가 입도 선행 필요 → 별도 스펙.
- **벡터/하이브리드 discover**: discover는 현행 lexical(부분일치) 유지. 카탈로그 작음(설계결정 10). 컬렉션이
  많아지면 후속. (컬렉션 *내부* 청크 검색은 이미 벡터 cosine — 이건 invoke의 코어가 담당, discover와 별개.)
- **top_k·재랭킹 튜닝**: 코어 기본값(4) 사용. 관련도 임계·멀티모델 정규화는 037/072의 기존 빚 유지.
- **admin UI 노출**: capabilities allowlist에 `rag:*` 편집 UI는 후속(Phase 2-d, backlog).
- **인-챗 RAG 도구(`vectorTables`)는 브로커 정책 밖 — 정직한 경계**(적대 리뷰 103 P1, OUT 기록):
  에이전트에 `vectorTables`로 직접 붙인 컬렉션은 기존 인-챗 도구(`build_rag_tool`, 스펙 037)로 검색된다.
  이 경로는 `capability:rag` RBAC를 **거치지 않는다** — 브로커 위임(`rag:` 능력)과는 **다른 신뢰 모델**이기
  때문이다: `vectorTables`는 *에이전트 저작자가 정의 시점에 묶는* 것(페르소나·모델·MCP 서버 선택과 동급,
  저작자 신뢰), `rag:` 능력은 *런타임 위임을 유저 RBAC로 게이트*하는 것. 103은 RAG를 **위임 능력으로
  추가**할 뿐, 기존 인-챗 도구를 브로커 뒤로 옮기지 않는다. 따라서 `capability:rag`가 없는 유저라도 그
  에이전트에 `vectorTables`가 있으면 일반 도구로 검색 가능 — **설계상 의도**(complement 공격이 찾은 비-브로커
  경로지만 안전 위반 아님, learning: complement-attack-can-be-honest-boundary). 브로커 rag 경로가 정책
  게이트됨은 verify_103 H4/H5가 단언(안전 불변식). 두 경로 통합은 별도 결정 사안.

## 설계

### cap_id 네임스페이스 + kind 파싱

- cap_id·allowlist 항목: **`rag:<collection_name>`**(mcp의 `mcp:server/tool`과 동형, 단 1레벨).
  `Collection.name`은 unique → 이름으로 키잉(vectorTables config가 이미 이름 목록 → 규칙 일관, drift 0).
- `_kind_of(item)`: 접두사 매칭을 rag까지 확장. `rag:`→rag, `mcp:`→mcp, 그 외(콜론 없는 bare `agt_...`)→agent.
  (하위호환: 기존 agent/mcp 판정 불변 — rag 접두사 분기만 추가.)
- `_parse_rag(item)`: `rag:<name>` → `<name>`(접두사 스트립). 이름에 콜론 있어도 첫 접두사만 제거해 안전.
- `CAP_KIND_RAG = "rag"` 상수 추가.

### RagProvider (`_CapabilityProvider` 구현)

McpProvider와 동형. `session_factory` 주입. 각 메서드:

- **`candidates(allow)`** — allow의 rag 항목 → `{collection_name}`. 없으면 `[]`(DB 미접촉). 있으면
  `SELECT Collection WHERE name IN names`(allowlist를 **SELECT WHERE에 밀어** 거부 대상 미로드 — 체크리스트
  §2 존재 오라클 차단). 각 행 → `Capability(id="rag:<name>", kind="rag", name=name, hook=설명 첫 줄)`.
- **`load(cap_id)`** — 이름 파싱 → `Collection`을 `embedding_model.provider`까지 selectinload. 미존재→None
  (존재 비노출). 존재하면 `_RagBacking(name, description, col)` 반환. `col` = retrieval 코어 계약 dict
  `{id, name, embed_base_url, embed_api_key(복호화), embed_model_id}` — **`chat._load_context`와 동일
  규칙**으로 구성(drift 0). 임베딩 모델/provider가 불완전하거나 `kind != embedding`이면 `col=None`
  (describe는 되게 두고, invoke가 graceful 오류로 표면화 — search_collection 400 가드와 동형).
- **`describe(row)`** — `Capability(id="rag:<name>", kind="rag", name, hook=설명 첫 줄, input_schema=
  {type:object, properties:{text:{string}, top_k:{integer}}, required:[text]})`.
- **`invoke(row, args)`** — `text = args["text"]`. `row.col is None`이면 graceful `InvokeResult(error=
  "컬렉션 임베딩 설정 불완전")`. 아니면 `search_collections([row.col], text, top_k)` 호출 →
  hits를 **공유 포맷터로** 텍스트 블록으로 접어 `InvokeResult(text=..., trust="untrusted")`.
  `RagSearchError`는 catch → graceful `error`(코어가 이미 분류; 에이전트를 죽이지 않음).
- **`node_label(row)`** — `f"broker_invoke:rag:{name}"`.
- **`approval_for(cap_id, args)`** — **항상 None**(RAG=읽기전용, 부수효과 없음 → HIL 불요). 이 한 줄이
  저위험의 핵심.

### 공유 포맷터(drift 0) — 결정

`build_rag_tool`의 hit→문자열 포맷 로직은 현재 도구 클로저 *내부*에 있다. RagProvider.invoke도 hit를
텍스트로 접으므로, 그대로 두면 **평행 구현 = drift**(072가 경계한 바로 그 함정). → `runtime.py`에
`format_rag_hits(results) -> str`를 **추출**(행위 보존 리팩터)하고 `build_rag_tool`과 RagProvider가 둘 다
호출. "엔드포인트는 초록인데 위임은 다름"을 원천 차단. (추출이 과하면 대안: provider가 자체 간결 포맷 —
단 그 경우 스펙에 "포맷 drift 허용 사유"를 명시. **기본은 추출**.)

### 등록 + 정책(무변경 확인)

- `PolicyScopedBroker._providers`에 `RagProvider(session_factory)` 추가. `_by_kind`는 자동 확장.
- `_permitted`: rag는 mcp 같은 서버/툴 2레벨이 아니라 1레벨 → agent와 동일하게 `cap_id in self._allow`.
  (`_permitted` 본체에 rag 분기 불요 — 기본 경로가 정확 매치. mcp만 서버-전체 덮기 특례.)
- `build_broker`의 RBAC: `enforce(id, f"capability:{kind}", "invoke")`가 kind="rag"를 **자동 처리**(무변경).
  seed 정책은 admin `('*','*')`만 → member는 `capability:rag` 거부(deny-by-default가 정책 부재에서 성립).
- discover: `_rbac_allows("rag")` 거부면 provider 아예 미호출(DB 미접촉, 존재 누출 0) — 기존 루프 그대로.

## RBAC/소유권 경계 체크리스트 — 상속으로 만족(why)

이 스펙은 정책 게이트(allowlist∩RBAC)를 건드리므로 체크리스트가 트리거된다. 단 **새 유저데이터 입구는 0**
이라 대부분 상속으로 답한다(102와 동형):
1. **입구 열거** — 브로커 입구는 discover/describe/invoke 셋(닫힌 집합). RagProvider는 이 셋 *뒤에서*
   호출될 뿐 새 입구를 열지 않는다. **부수효과 입구 0**(read-only) → delete/resume/lazy-create 해당 없음.
2. **입구별 소유권** — `Collection`은 owner 없는 공유 카탈로그(명시 경계, 비목표). 소유권 판정 대상 아님.
   candidates는 allowlist를 **SELECT WHERE에** 밀어 거부행 미로드(§2 준수).
3. **단일 헬퍼** — 정책 판정은 여전히 브로커 `_permitted` 단일 지점. RagProvider는 정책 미접촉(드리프트 0).
4. **존재 비노출** — 미허가·미존재 모두 `_resolve`→`CapabilityNotFound`/not-found로 접힘(기존 경로 상속).
5. **검증 사다리 3런** — 아래 검증 참조.
6. **자가-잠금 핀** — 허가된 rag cap을 정당 유저가 실제로 발견·호출 가능한지 별도 단언(과도 조임 방지).

## 검증

`tests/verify_103_rag_provider.py`(runtime 먼저 import — 순환 방지 규약).

- **① 단위 시맨틱**(실 LLM/DB 없이 결정성):
  - `_kind_of("rag:docs")=="rag"`, mcp/agent 판정 무회귀. `_parse_rag` 라운드트립.
  - candidates: allow에 rag 항목 없으면 `[]`. describe input_schema 모양.
  - `_permitted("rag:x")`: allow에 있고 RBAC 허용 → True; RBAC 거부 → False; allow 밖 → False.
  - approval_for 항상 None(read-only 불변).
  - 셋째-provider 시임 측정: `RagProvider`가 `_CapabilityProvider` 6메서드 계약 충족(agent/mcp와
    동일 시그니처) — 시임이 셋째에도 안 샘.
- **② 실 인프라 통합**(seed + 실 검색, verify_072 선례):
  - mock 임베딩 provider·embedding 모델·Collection 시드 → 문서 인제스트(결정적 벡터) → allowlist
    `rag:<name>` + RBAC 허용 브로커.
  - `discover("...")` → rag cap 노출. `invoke("rag:<name>", {"text": q})` → 상위 청크 텍스트,
    trust=untrusted, `broker.invocations`에 `broker_invoke:rag:<name>` 1프레임.
  - **정책 격리**: RBAC가 rag 거부면 discover에 rag cap 0(DB 미접촉). allow 밖 이름 invoke → not-found
    (존재 비노출).
  - **공유 코어 drift 0**: 같은 컬렉션·질의에 대해 `build_rag_tool` 경로와 provider invoke가 동일 상위
    청크를 반환(포맷터 공유 실증).
- **③ 적대 타자(codex)**: "보장 목록의 여집합". 예상 표적 — (a) rag cap_id로 다른 kind/컬렉션 우회
  가능한가, (b) 미허가 컬렉션 이름 열거 오라클, (c) untrusted 결과가 SystemMessage로 새는가(100 격리
  회귀), (d) 이름 파싱 엣지(콜론/슬래시 포함 이름). codex 파일 경계 프리픽스 적용(~/.claude, agents/ 등 접근 금지).

## 완료 조건

- verify_103 전 런 ok(단위+통합), 무회귀(verify_072/100/101/102).
- codex 여집합 리뷰 트리아지 완료(실결함 수정 / 오탐 기각 / 미문서 경계 명시 — 3판정).
- 회고 `.dev/retrospect/084-*` + learning(해당 시) + 각 INDEX 한 줄 + per-spec 커밋.
