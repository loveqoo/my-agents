# 101 — 능력 브로커 kind 확장: MCP provider (Phase 2-a)

> Status: **draft**(AI 초안 — 인간 검토 대상). 스코프 미승인(검토 대기).
> 참고 자산: spec 100(브로커 Phase 1 — 정책 게이트·시임)·retrospect 081·054(MCP 실연결 런타임·
> langchain-mcp-adapters·self-host mock_mcp)·093/`references.py`(MCP name 참조·삭제가드)·087/092
> (MCP args/result redaction·raw 숨김)·064/`net_guard`(SSRF·mcp_http_client_factory 리다이렉트 하드닝)·
> learning 100(신뢰불가 데이터=데이터 채널)·099(확장점 위치·순수함수·수용게이트 재사용).

## 1. 배경 / 문제

스펙 100은 능력 브로커를 **1개 시임**(`discover/describe/invoke`)으로 세웠으나 provider는 kind=`agent`
(A2A) 하나뿐이다. "A2A·MCP·RAG·memory는 4개 기능이 아니라 1개 시임"이라는 **핵심 주장은 아직
미증명** — 두 번째 kind가 붙어야 시임이 진짜 여러 종류를 담는지 실증된다.

MCP는 이미 완전한 병렬 인프라가 있으나(모델 `McpServer`·CRUD `blocks.py`·전송 `runtime.build_mcp_tools`
+`MultiServerMCPClient`·SSRF `net_guard`) **브로커와 다른 축**에 있다: MCP는 그래프 빌드 시점에
**preload되는 tools**(`ctx.tools`), 브로커는 **동적 discover→invoke**(`ctx.broker`). 이 둘은 지금 안 만난다.

**진짜 갭:** MCP를 브로커의 두 번째 provider로 얹어, 에이전트가 MCP 툴을 *preload가 아니라 discovery로*
그때그때 찾아 서브스텝 호출하게 한다. 동시에 provider 시임을 도입해 kind 확장이 정책 게이트를 흩뜨리지
않음을 구조로 보장한다.

## 2. 스코프 (Phase 2-a)

**IN:**
1. **provider 시임 리팩터** — `PolicyScopedBroker` 안에 내부 `CapabilityProvider` 인터페이스 도입.
   정책(allowlist∩RBAC·deny-by-default·존재비노출·단일 `_permitted`)은 브로커에 남기고, kind별
   메커닉(후보 나열·cap 로드·invoke 전송·hook·input_schema)을 provider로 이관. `AgentProvider`는
   기존 A2A 코드를 **행위 보존**으로 옮긴다(리팩터=無행위변경, verify_100 그대로 통과가 게이트).
2. **`McpProvider`(신규)** — kind=`mcp`. 모집단=`McpServer` 행, 후보=**enabled_tools 단위**(툴 하나=능력
   하나), hook=툴 description, input_schema=툴 inputSchema. invoke=`MultiServerMCPClient`로 해당 툴
   1회 호출→텍스트 접기→`InvokeResult(untrusted)`. 전송/SSRF는 `net_guard.mcp_http_client_factory`
   (리다이렉트 하드닝) 재사용.
3. **allowlist 네임스페이싱** — 에이전트 config `capabilities`가 agent cap과 mcp cap을 구분해 담는 규약
   확정(§3.3). 기존 bare id(=agent)는 하위호환 유지.
4. **정책 게이트 kind 재사용** — RBAC 축은 이미 `_permitted(cap_id, kind)`·`rbac_allows(kind)`로
   파라미터화됨(spec 100). MCP는 `capability:mcp invoke` enforce를 그대로 탄다. 신규 정책 코드 0.
5. **데모 재사용** — 기존 `orchestrate` flow가 kind 무관하게 broker로 발견→invoke→종합하므로,
   MCP cap만 allowlist에 있는 에이전트로 같은 flow가 MCP를 서브스텝 호출함을 실증(신규 flow 0).
   `build_synthesis_messages` 채널 격리(learning 100)가 MCP 결과에도 그대로 적용됨을 확인.
6. **브로커 서브스텝 HIL(권한 승인) 지원** — 위임한 MCP 툴이 실행 중 승인을 요구하면(예:
   `local-tools/delete_record`), 조용히 실행/건너뛰지 않고 그 요청을 사용자에게 올려 승인받고 재개한다.
   기존 HIL 파이프라인(`interrupt()`→`__interrupt__`→SSE→Approval→`Command(resume)`)을 **그대로 재사용**
   (§3.5). 승인 정책은 그래프-tools 경로와 **동일 소스**(`_APPROVAL_ACTIONS`)를 써 드리프트 0.

**OUT(후속):** RAG·memory kind(각 후속), 벡터/하이브리드 discover(카탈로그 작아 lexical 유지, 설계결정
10), per-cap·per-user 인가+에이전트 소유권(spec 100 §6 그대로 이연), admin UI capabilities 편집(Phase 2-d).

## 3. 설계

### 3.1 provider 시임 (packages/api/broker.py 내부)

```
class _CapabilityProvider(Protocol):        # 브로커 내부 전용(계약 packages/agent는 불변)
    kind: str
    async def candidates(self, allow: set[str]) -> list[Capability]:  # allowlist∩모집단 → 후보(hook 채움)
        ...
    async def load(self, cap_id: str) -> object | None:  # 허가 전제, cap_id→backing row(미존재→None)
        ...
    def describe(self, row) -> Capability:               # row→input_schema 채운 Capability
        ...
    async def invoke(self, row, args: dict) -> InvokeResult:  # 전송 1회→텍스트 접기(untrusted)
        ...
```

- `PolicyScopedBroker`는 `{kind: provider}` 맵을 들고, cap_id에서 **kind를 파싱**(§3.3)해 해당 provider로
  라우팅. 정책 판정(`_permitted`)은 브로커가 provider **호출 전에** 수행 — provider는 정책을 모른다
  (게이트 단일 지점 유지, 체크리스트 §3 드리프트 0).
- `discover`: 각 provider `candidates(self._allow)` 합집합 → lexical 필터 → limit. deny-by-default
  (allow 비었거나 RBAC 거부 시 DB 접촉 전 공집합) 불변.
- `describe`/`invoke`: `_load_permitted(cap_id)`가 `_permitted` 후 kind별 provider `load` 위임. 미허가·
  미존재·kind 불명 모두 None→`CapabilityNotFound`/not-found(존재 비노출, 체크리스트 §4).

### 3.2 McpProvider

- **모집단**: `select(McpServer).where(McpServer.name.in_(허용 서버명))`. 후보 나열은 각 서버의
  `enabled_tools`(없으면 `tools`)를 순회, 툴 하나당 `Capability(id=f"mcp:{server}/{tool}", kind="mcp",
  name=tool, hook=툴 description 첫 줄)`.
- **load**: cap_id 파싱→(server, tool). 서버 행 조회+SSRF `guard_url`. 툴이 서버 tools에 있고 enabled면
  반환, 아니면 None(존재 비노출).
- **describe**: 툴 inputSchema를 `Capability.input_schema`로(A2A의 고정 `{text}`와 달리 툴별 실제 스키마).
- **invoke**: `MultiServerMCPClient({server: 연결dict})`로 `get_tools(server_name=server)`→해당 tool 선택→
  `tool.ainvoke(args)`→결과를 `_content_text`(092 정규화 재사용)로 텍스트 접기→`InvokeResult(untrusted)`.
  연결 dict는 `runtime.build_mcp_tools`의 것 재사용(transport=streamable_http·Bearer·
  `httpx_client_factory=net_guard.mcp_http_client_factory`). **툴 wrapping(트레이스·HIL)은 안 씀** —
  브로커는 단발 one-shot이라 얇은 invoke 경로(신규, 그러나 전송·SSRF는 기존).
- 관측: `self.invocations.append({"node": f"broker_invoke:mcp:{server}/{tool}", ...})`. **args/result는
  프레임에 안 담음**(087/092 — MCP 원문 누출 0).

### 3.3 allowlist 네임스페이싱

- 규약: allowlist 항목은 `"<kind>:<id>"`. `mcp:<server>/<tool>`(툴 단위) 또는 `mcp:<server>`(서버 전체=
  그 서버 enabled_tools 전부). **접두사 없는 bare 항목 = kind `agent`**(하위호환; spec 100 config 불변).
- cap_id 자체도 같은 네임스페이스라 라우팅이 id만으로 결정(별도 조회 없이 kind 파싱).
- `_permitted`: agent는 `cap_id in allow`(기존). mcp는 `cap_id in allow` **또는** `mcp:<server> in allow`
  (서버 전체 허용이 그 툴을 덮음) — 단일 헬퍼 안에서 kind별 매칭(드리프트 0 유지).

### 3.4 데모(재사용 실증)

- `orchestrate` flow 코드 변경 0. allowlist에 `mcp:<server>/<tool>`만 담은 에이전트를 seed→같은 flow가
  `analyze→delegate(MCP discover→invoke)→synthesize` 실행. 트레이스 graph에
  `broker_invoke:mcp:<server>/<tool>` 노드가 뜸(kind=mcp 서브스텝 실증).
- self-host mock_mcp(spec 054)를 provider로 써 실 MCP 왕복 검증.

### 3.5 HIL(권한 승인) 서브스텝 지원

**핵심:** 위임한 MCP 툴이 승인을 요구하면 그 요청이 부모(orchestrate) 그래프를 pause시켜 사용자에게
올라가고, 승인 후 재개돼 실행된다. LangGraph 계약상 `interrupt()`는 노드가 호출한 코루틴 내부에서
불러도 부모 그래프를 pause한다 — 이것이 **정확히 현 MCP 게이트가 하는 일**(`_wrap_mcp_tool._run` 내부
`interrupt`가 ReAct 부모를 멈춤). 브로커 서브스텝은 같은 패턴을 탄다.

- **게이트 위치 = 브로커 단일 지점(정책 무지 provider 위)**: `PolicyScopedBroker.invoke`가 전송 위임
  **전에** provider에게 승인 필요 여부를 묻고, 필요하면 `interrupt(payload)`를 호출한다.
  ```
  # PolicyScopedBroker.invoke (재검증 _permitted 통과 후)
  approval = provider.approval_for(cap_id, args)   # (permission, summary) | None
  if approval:
      decision = interrupt({... payload ...})       # 부수효과 이전(멱등)
      if decision.get("decision") != "approve":
          return InvokeResult(text="거부됨 …", trust="untrusted")
  return await provider.invoke(row, args)           # 승인된 경우만 전송(부수효과 1회)
  ```
  이로써 **모든 flow가 브로커를 쓰면 HIL을 공짜로** 얻는다(flow 저작자 재구현 0). 게이트 단일화 유지.
- **승인 정책 = 단일 소스 재사용(드리프트 0)**: `McpProvider.approval_for`는 기존
  `_APPROVAL_ACTIONS[(server, tool)]`(runtime.py)를 **그대로 조회**한다. 그래프-tools 경로와 브로커
  경로가 같은 정책을 봐, 툴을 *어느 경로로 부르든* 승인 요건이 일치한다. payload 마스킹도 기존
  `_redact_args` 재사용(별도 정책이 갈라지지 않게). `AgentProvider.approval_for`는 Phase 2-a에서
  `None`(A2A 위임 승인은 정책 소스 없음 — 후속). → 게이트는 per-provider 정책, interrupt는 단일 지점.
- **멱등 불변식(체크리스트 §2 재확인)**: `interrupt`는 **전송(부수효과) 이전**에 둔다. 재개 시
  orchestrate가 체크포인트에서 `delegate` 노드를 재실행 → `discover`(읽기전용) 재호출·`invoke` 재진입 →
  `interrupt`가 이번엔 decision 반환 → 전송 1회. MCP `_wrap_mcp_tool`의 "interrupt 이전 부수효과 0"
  불변식과 동일.
- **매니페스트 정직화**: `orchestrate.describe().supports_hil`을 `True`로(현 `False`). 안 그러면 resume
  drift 가드(chat.py)가 재개를 거부하고, 089 conformance의 매니페스트 정직성과도 어긋난다(이제 실제로
  HIL 지원하므로 True가 정직).
- **배선 이미 완비(재사용)**: orchestrate는 이미 `g.compile(checkpointer=ctx.checkpointer)`(orchestrate.py
  :146). `interrupt`→`__interrupt__` 수집→Approval 생성→`POST /approvals/{id}/resolve`→
  `Command(resume={"decision":...})` 파이프라인(chat.py·approvals.py)이 완결돼 있어 **새 배선 0**.
- broker_invoke 프레임은 args/result를 안 담아 087/092 redaction 표면과 무관(누출 0). interrupt payload는
  `_redact_args`로 마스킹된 args만 싣는다.

**제약(플랫폼 기존 한계, 신규 아님):** (a) 한 턴 **단일 interrupt만** — 다중 승인은 error로 닫힘
(chat.py). orchestrate는 delegate 1회=invoke 1회라 Phase 2-a 안전(여러 서브스텝 게이팅은 §6 후속).
(b) 재개 시 **라이브 스트리밍 없음** — resume는 서버사이드 run-to-completion 후 결과 영속(기존 빚).

## 4. RBAC/소유권 경계 체크리스트 (이 스펙 = 인가 경계)

1. **입구 열거(닫힌 집합):** `discover`/`describe`/`invoke` 3개 × kind{agent,mcp} + flow의 `ctx.broker`.
   외부 프로토콜 입구는 provider별 하나(agent=a2a_stream, mcp=MultiServerMCPClient) — 둘 다 net_guard
   `guard_url` chokepoint 경유(신규 SSRF 입구 0).
2. **입구별 게이트:** 셋 다 `_permitted`(allowlist∩RBAC). invoke는 호출 경계 재검증(TOCTOU). provider는
   정책 무지 — 게이트는 브로커 단일 지점. cap 모집단은 SELECT-WHERE로 스코프(비-SQL 우회 없음).
   **HIL 게이트도 브로커 단일 지점**: `interrupt`는 전송(부수효과) 이전(멱등 — 재개 시 재실행돼도 전송
   1회). 승인 정책은 `_APPROVAL_ACTIONS` 단일 소스(그래프-tools와 브로커가 같은 요건 = 드리프트 0).
3. **단일 헬퍼:** `_permitted(cap_id, kind)` 하나로 agent·mcp 판정 통일(kind별 매칭은 헬퍼 *내부*,
   드리프트 0). provider 라우팅은 판정 **후**.
4. **존재 비노출:** allowlist∩RBAC 밖은 discover 미노출, describe/invoke는 not-found로 접음(kind
   불명·미존재·미허가 동일 처리). 403/404 구분 없음.
5. **검증 사다리 3런(비겹침):** ①단위(provider 라우팅·네임스페이싱 파싱 순수함수·정책 판정 시맨틱·
   `approval_for` 정책 판정·행위보존 리팩터=verify_100 무회귀)·②실 인프라 통합(seed된 허용/비허용 MCP
   서버+실 mock_mcp 왕복+실 flow 스트림의 mcp 서브스텝 노드 + **HIL 왕복**: interrupt→Approval→resolve
   approve/reject 실 재개)·③codex 적대("보장 여집합": kind 라우팅 우회·MCP 원문 누출·서버전체 허용이
   비허용 서버 툴로 새는지·존재 오라클·**승인 이전 부수효과 발생 여부**).
6. **자가-잠금 핀:** 정당하게 허용된 MCP 툴은 정상 발견·호출됨(조임이 본인 접근 안 막음). 리팩터가
   기존 agent cap 경로를 안 깼음(verify_100 그대로 green).
7. **HIL 멱등:** 승인 요구 툴은 `interrupt` **이전 부수효과 0**(재개 재실행에도 전송 1회) — `_execute`
   호출 횟수로 실측(MCP 게이트 불변식 재사용).

## 5. 완료조건 (측정가능, 데모 주도)

- **행위보존 리팩터:** provider 시임 도입 후 `verify_100_broker.py` **무회귀**(agent 경로 불변 증명).
- **MCP discover:** allowlist에 `mcp:<server>/<tool>` 담은 에이전트가 그 툴을 discover 결과로 받음
  (bare agent cap과 kind로 구분됨).
- **MCP invoke 서브스텝:** orchestrate 트레이스 graph에 `broker_invoke:mcp:<server>/<tool>` 노드 포함
  (kind=mcp가 실제 서브스텝으로 조립됨).
- **deny-by-default:** allowlist 밖 MCP 서버·툴은 discover 없음. **서버전체 허용(`mcp:<server>`)이 다른
  서버 툴을 안 덮음**(적대 시드로 실증).
- **untrusted 격리:** mock MCP가 인젝션 페이로드 반환해도 InvokeResult.trust=="untrusted" 유지+
  `build_synthesis_messages`가 데이터 채널로 격리(learning 100이 kind 무관 유효).
- **원문 누출 0:** broker_invoke 프레임에 MCP args/result 원문 없음(단언).
- **RBAC 교집합:** `capability:mcp invoke` enforce 실패 유저는 MCP cap discover 없음.
- **HIL 서브스텝:** 승인 요구 MCP cap(예 `local-tools/delete_record`)을 orchestrate가 위임하면 (a)
  `interrupt`가 부모 그래프를 pause시켜 pending Approval이 생성됨, (b) `/approvals/{id}/resolve` approve →
  재개 후 전송 1회 실행·결과가 종합에 반영, (c) reject → 부수효과 0·거부 메시지, (d) 승인 이전 `_execute`
  호출 0(멱등 실측). `orchestrate.supports_hil==True`가 정직(089 conformance).
- **무회귀:** verify_085/089/100 통과. codex 적대 no P0/P1.

## 6. 비목표

- RAG·memory kind(각 후속 스펙). Phase 2-a는 kind={agent, mcp}.
- 벡터/하이브리드 discover(카탈로그 규모 커질 때, 설계결정 10).
- per-cap·per-user 인가 + 에이전트/MCP 소유권(spec 100 §6 그대로 — McpServer도 owner 없는 공유 카탈로그.
  기본 정책 admin-only라 deny-by-default 성립, member에 `capability:mcp` 주면 접근 가능 서버 전부 호출).
- **A2A(agent) cap 위임 승인** — Phase 2-a HIL은 MCP cap만(정책 소스 `_APPROVAL_ACTIONS` 재사용).
  `AgentProvider.approval_for`는 `None`. "에이전트 X에 위임 승인" 정책 소스는 후속.
- **한 턴 다중 서브스텝 승인** — 플랫폼이 단일 interrupt만 지원(chat.py). orchestrate는 delegate 1회라
  무관하나, 여러 cap을 게이팅하는 flow는 후속(다중 승인 프로토콜).
- **재개 라이브 스트리밍** — 기존 빚(resume=서버사이드 run-to-completion). 이 스펙 범위 밖.
- admin UI capabilities allowlist 편집(Phase 2-d).
- 런타임 동적 MCP 등록(등록=저작시점·정적, 신뢰경계 보존).
