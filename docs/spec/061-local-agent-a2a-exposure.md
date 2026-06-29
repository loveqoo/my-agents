# 061 — 로컬(ui) 에이전트를 실제 A2A로 노출 (exposed.a2a 실동작화)

> 상태: **초안(AI 작성, 인간 검토 대기)**. 작업 방식 = CLAUDE.md 6단계 루프.
> 짝 스펙: [060](060-a2a-playground-endpoint-normalization.md)(정규화 + 로컬테스트 UX) — 060이 등록·호출
> 경로를 매끄럽게 하고, 061이 **호출 대상(실 로컬 A2A 서버)** 을 만든다. 함께 "내 에이전트를 A2A로
> 등록해 플레이그라운드에서 실왕복 테스트"를 성립시킨다.

## 1. 문제 (코드로 확정)

`exposed.a2a` 플래그는 **무력(inert)** 하다:
- `models.py`: `Agent.exposed = {"a2a": bool}` 필드 존재.
- `agents.py:279` `PUT /{agent_id}/expose`: 플래그를 **저장만** 한다.
- **그 플래그를 읽어 로컬 에이전트를 A2A로 *서빙*하는 엔드포인트가 없다.** grep 결과 JSON-RPC A2A
  서버는 `mock_remote.py:262`(`/_remote/a2a`) **canned mock 하나뿐** — 입력과 무관한 고정 응답.

따라서 사용자가 "로컬 에이전트를 임시로 A2A로 열어 등록·테스트"하려 해도 **열 대상이 없다**. 이는
플랫폼 핵심 가치(자기 에이전트를 A2A로 협업 노출 — 메모리 `why-build-multi-agent-platform`)의 토대가
비어 있다는 뜻이다.

## 2. 합의된 방향 (2026-06-29)

- **실제로 만든다**(사용자 선택). `exposed.a2a=True`인 로컬(ui) 에이전트를 **기존 로컬 LangGraph
  런타임을 그대로 돌려** A2A JSON-RPC + well-known 카드로 서빙한다. canned mock이 아니라 실 런타임.
- 스펙 분리: **060**=정규화+UX, **061**(본 문서)=실 노출. 각각 독립 단위·per-spec 커밋.

## 3. 설계

### 3.1 라우팅 — 새 비인증 라우터 `a2a_server.py`

`agents.router`/`chat.router`는 `dependencies=[Depends(current_principal)]`로 **전역 인증**된다
(main.py:75-80). 그런데 등록 시 우리 서버가 *자기 자신의 카드를 fetch*하는데(`agent_card.fetch_card`는
**인증 헤더를 안 보냄**), 카드 엔드포인트가 전역 인증 뒤에 있으면 self-fetch가 401로 깨진다. 그래서
A2A 서빙 라우트는 `mock_remote`처럼 **전역 인증 없이** 별도 라우터로 마운트하고, 인증은 **JSON-RPC
호출 라우트에만 라우트 단위로** 건다.

```
app.include_router(a2a_server.router)   # main.py — _auth 미적용(mock_remote와 동일 줄)
```

라우트(둘 다 prefix `/agents`, well-known 관례가 자연스럽게 맞게):

1. **`GET /agents/{agent_id}/.well-known/agent-card.json`** — **공개**(인증 없음).
   - 게이트: 에이전트 존재 + `source == "ui"` + `exposed.a2a is True`. 하나라도 아니면 **404**
     (노출 안 된 에이전트의 존재/구성을 누출하지 않음 — fail-closed).
   - 카드 본문:
     ```json
     {
       "name": <agent.name>,
       "description": "...(로컬 에이전트 A2A 노출)",
       "url": "<self_base>/agents/<agent_id>/a2a",
       "version": <active_version or "1.0.0">,
       "capabilities": {"streaming": true, "pushNotifications": false},
       "defaultInputModes": ["text/plain"], "defaultOutputModes": ["text/plain"],
       "skills": [{"id": "chat", "name": <agent.name>, "description": "...", "tags": ["chat"]}]
     }
     ```
   - **`x-my-agents` 확장은 넣지 않는다** → `connect`가 **external(불투명 제3자)** 로 분류. v1은 등록된
     사본을 별개 원격 핸들로 다룬다(제1자 자기인식=code 분류는 범위 밖, §6). 두 분기 모두 런타임은
     `_a2a_stream` 하나라 분류는 표시 차이일 뿐(chat.py:447 주석).

2. **`POST /agents/{agent_id}/a2a`** — **인증**(`Depends(current_principal)`: 쿠키 유저 또는 머신 토큰).
   - 같은 게이트(ui + exposed). 아니면 404.
   - JSON-RPC 2.0 파싱: `method`·`id`·`params`. `params.message.parts[].text`(kind=="text")를 모아
     user_text(입력 형태는 `mock_remote._a2a_user_text`와 동형).
   - **로컬 런타임 실행**(§3.2) → 응답 텍스트.
   - `message/send` → 단건 `JSONRPCResponse`(result = Message{role:agent, parts:[text]}).
   - `message/stream` → SSE `status-update` 이벤트들(텍스트 청크) + 마지막 `final:true, state:"completed"`
     + `data: [DONE]`. 프레임 형태는 `mock_remote.remote_a2a`의 `_status_event`와 **동형**(a2a_client가
     이미 파싱하는 계약).
   - 미지원 메서드 → JSON-RPC error `-32601`.

3. **self_base 결정** `_self_base(request)`:
   - env `A2A_SELF_BASE_URL`(설정 시, trailing `/` 제거) 우선, 없으면 `str(request.base_url).rstrip("/")`.
   - 카드 `url`은 이 절대 http(s) base로 구성 → 060 정규화와 무관히도 절대 URL 보장(이중 안전).

### 3.2 로컬 런타임 재사용 — `chat.stream_local_reply`

`chat.py`에 집중 헬퍼를 **추가**(기존 `chat()`/`event_stream()`은 **무변경** — 핵심 채팅 경로 무회귀):

```python
async def stream_local_reply(agent_id: uuid.UUID, user_text: str):
    """로컬(ui) 에이전트를 A2A 서빙용으로 실행 — 텍스트 청크만 yield.
    _load_context + build_agent + graph.astream("messages") 재사용. v1은 persist/HIL/자동 memory-add
    미적용(노출 런타임=순수 컴퓨트; 영속은 호출측 _a2a_stream이 자기 세션에 한다). 위험 도구는
    checkpointer=None이라 fail-closed(승인 게이트는 노출 경로에 없음 — §6)."""
```
- `_load_context(agent_id, None)`로 ctx 확보. `ctx["source"]`가 ui가 아니면 `ValueError`(라우트가 404/400).
- 메모리 회상은 v1 생략(범위 밖, §6) — persona/model/tools/RAG는 그대로 합성.
- `build_mcp_tools` + (rag 있으면)`build_rag_tool` → `build_agent(persona, params, tools, model_cfg,
  checkpointer=None)` → `astream(stream_mode=["messages"])`에서 텍스트 청크 yield.
- 모델 연결 실패 등 예외는 호출 라우트가 JSON-RPC error로 변환(자격증명 미에코 — a2a_client 규칙 준용).

### 3.3 호출 흐름(실왕복 dogfood)

```
플레이그라운드(external 사본 채팅)
  → chat.chat() source=external → _a2a_stream
  → a2a_client.a2a_stream(endpoint=<self>/agents/<id>/a2a, token)  [guard_url: loopback→A2A_ALLOWED_HOSTS 필요]
  → POST /agents/<id>/a2a (auth: 머신토큰)  [본 스펙의 서버]
  → chat.stream_local_reply(<원 로컬 에이전트>)  → 실 LangGraph 런타임
  → status-update SSE → a2a_client 파싱 → 우리 SSE → 플레이그라운드 렌더
```
- 등록은 카드 base `<self>/agents/<id>`를 `/agents/connect`에 입력 → fetch_card가 well-known 관례로
  `…/.well-known/agent-card.json`을 찾음. 카드 `url`=`…/agents/<id>/a2a`가 호출 endpoint로 저장.
- 토큰: 등록 시 **머신 토큰**(`.dev/.api_token`)을 connect의 token으로 주면 a2a_client가
  `Authorization: Bearer`로 실어 JSON-RPC 라우트의 `current_principal`을 통과한다(루프백 dogfood).
- 루프백 host(127.0.0.1)는 SSRF 가드가 기본 차단 → `A2A_ALLOWED_HOSTS=127.0.0.1` 필요(060이 발견 가능
  하게 메시지·.env.example로 안내).

### 3.4 UI(admin) — 노출 카드 URL 노출

- AgentsView의 노출 토글(`exposed.a2a`) 옆/모달에, 토글 ON일 때 **카드 URL을 복사 가능**하게 표시:
  `{API_BASE}/agents/{agent_id}/.well-known/agent-card.json`(또는 base `…/agents/{agent_id}`). 사용자가
  이 URL을 그대로 connect에 붙여 테스트한다. (없으면 사용자가 URL을 손으로 조립해야 함 — UX 벽.)
- 060 B2(연결 모달 allowlist 힌트)와 합쳐 "노출→복사→연결→테스트" 한 흐름.

## 4. 완료 조건 (측정 가능)

- **D1**: `exposed.a2a=True`인 ui 에이전트의 `GET …/.well-known/agent-card.json` → 200 + 유효 카드
  (`validate_card` 통과, `url`이 절대 http(s)·`…/a2a`로 끝남).
- **D2**: `exposed.a2a=False` 또는 source!=ui 또는 미존재 → 카드·JSON-RPC 둘 다 **404**(누출 없음).
- **D3**: `POST …/a2a` `message/send`(인증) → JSON-RPC result Message에 **실 런타임 응답 텍스트**
  (mock 고정문구 아님 — 입력 의존). 무인증 → 401.
- **D4**: `message/stream`(인증) → status-update SSE 청크들 + final + `[DONE]`, a2a_client가 파싱해
  비어있지 않은 텍스트 추출.
- **D5 (실왕복 E2E)**: ui 에이전트 노출 → 그 카드 URL을 `/agents/connect`로 등록(external 분류) →
  `A2A_ALLOWED_HOSTS=127.0.0.1` 하에 그 external 사본을 채팅 → **원 로컬 에이전트의 실 응답** 수신.
- **D6 (보안)**: 미인증 `POST …/a2a`=401; 노출 토글 OFF면 즉시 404로 회귀(런타임 미실행).
- **D7 (UI)**: 노출 토글 ON 시 admin에 카드 URL이 복사 가능하게 노출.

## 5. 검증 (타자 우선)

- 단위: `tests/verify_061_*` — 카드 게이트(D1/D2), JSON-RPC send/stream 형태(D3/D4 표면), 인증 게이트(D6).
- 통합/E2E: 이 호스트 라이브 부팅으로 D5(노출→connect→chat 실왕복) 실측 + 브라우저 스샷 D7
  (메모리 `verify-ui-in-browser-proactively`).
- 적대: codex 리뷰 — **새 인바운드 표면**이므로 필수(메모리 `adversarial-review-before-destructive-ship`,
  `installed-guard-isnt-covering-guard`). 점검축:
  - 인증 우회: 카드는 공개여야(self-fetch) 하나 JSON-RPC는 무인증 401인지, 게이트(ui+exposed)가
    **두 라우트 모두**에 동일 적용되는지(한쪽만 막으면 누출/무단실행).
  - 게이트 회피: source 위조·exposed 토글 경합·미존재 id로 런타임이 도는 경로 없는지.
  - SSRF 상호작용: self_base가 외부 입력(Host 헤더)으로 오염돼 카드 url이 공격자 제어 호스트를
    가리킬 수 있는지(env 우선·request.base_url 신뢰 경계).
  - 자원: 무한/거대 응답이 서버측에서 캡 없이 흐르는지(클라 캡은 a2a_client에 있음 — 서버측도 점검).
  - 자격증명 에코: JSON-RPC error 메시지가 토큰/내부정보를 누출하지 않는지.
- **codex 적대 리뷰 결과(2026-06-29)**: 인증 우회·게이트 누출·normalize→guard 우회·자격증명 에코·
  chat() 회귀 — **구체적 결함 없음**(codex 명시). 발견 2건:
  - **H1(High) Host 헤더 오염**: `_self_base`가 env 미설정 시 `request.base_url`(Host 파생)을 무조건
    신뢰 → `Host: attacker.example`로 카드 url 오염, 등록되면 이후 호출이 프롬프트·Bearer 토큰 유출.
    **이번에 수정** — env 미설정 폴백을 `net_guard.host_is_private`로 **로컬/사설 Host에 한정**, 공인
    Host는 503 fail-closed(A2A_SELF_BASE_URL 강제). 단위 H1 + verify로 회귀 차단.
  - **H2(Medium) 미분류 MCP 부수효과 도구 무승인 실행**: `_APPROVAL_ACTIONS` 밖 도구는 A2A 경로에서
    승인 없이 실행. **chat() 기존 동작과 동일**(권한 상승 아님)·인증 게이트 동일·분류된 위험 도구는
    checkpointer=None로 fail-closed. v1은 §6대로 문서화 후속(읽기전용 allowlist는 추후 하드닝).

## 6. 범위 밖 (명시)

- **제1자 자기인식**: 노출 카드에 `x-my-agents` 확장을 실어 connect가 code로 분류·매니페스트 import
  하는 것. v1은 external(불투명)로 충분(런타임 동일). 별도 스펙.
- **노출 경로의 HIL 승인 게이트·자동 memory-add·세션 영속**: v1 서빙은 순수 컴퓨트(persist는 호출측).
  분류된 위험 도구(`_APPROVAL_ACTIONS`)는 checkpointer=None로 fail-closed(interrupt() 실패→미실행).
  단 **미분류 부수효과 MCP 도구는 승인 없이 실행**된다(codex H2) — 이는 chat() 기존 동작과 동일하고
  인증 게이트도 동일하므로 A2A가 권한을 상승시키진 않는다. 노출 런타임에 승인/메모리 패리티(또는
  읽기전용 도구 allowlist)는 후속 스펙.
- **노출 경로의 멀티턴 contextId 영속**: 호출측이 contextId를 보내지만 서빙측은 v1에서 무상태.
- **공개 인터넷 노출 하드닝**(레이트리밋·토큰 스코프 분리·카드 서명). v1은 인증된 tailnet/루프백 전제.
