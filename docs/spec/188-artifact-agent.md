# 188 — 산출물형 에이전트 뼈대 (ArtifactAgentBase)

## 배경·동기 (2026-07-06 논의)
"특정 산출물을 만들기 위해 노력하는 에이전트"가 필요하다. 단, **구체 로직을 가진 에이전트를 만드는 게
아니라**(사용자 교정) — *이런 기능을 추상적으로 제공하고 알맹이를 유저가 정의*할 수 있어야 한다.

추상화 수준(사용자 정의):
> 에이전트 하나를 만드는데, **어떤 로직을 실행해서 산출물이 나왔어. 그 산출물을 어떻게 처리했어.**
> 이 정도의 추상화. "어떤 로직"을 구체 구현하면 → RAG 검색, Entity ID 추출 후 API 호출, Form 렌더링,
> 유저 입력 반복. **우리는 이 뼈대를 만든다.**

### 설계 기둥 (논의 확정)
- 수명주기 = **produce(로직 실행) → artifact(산출물) → sink(처리)**. 뼈대가 수명주기를 소유,
  유저가 produce를 정의, sink는 설정으로 교체(API 호출·임베딩 UI JS 콜백 등 "정의하기 나름").
- **역할 경계**: LLM=추출·문구(produce가 프리미티브로 호출) / 코드(뼈대)=검증·완료·싱크 발사.
- 계보: **스펙 102 패턴의 재적용** — OrchestrationAgentBase가 골격(채널 격리·HIL·정책)을 소유하고
  자식의 유일 구멍이 `select()`였듯, ArtifactAgentBase가 골격을 소유하고 유일 구멍은 `produce()`.
- **이중 입력 일급(사용자 강조)**: 유저 입력은 채팅 텍스트와 폼 입력 **두 입구가 항상 열려** 있다.
  폼이 떠 있어도 텍스트로 답하면 그 값이 같은 빈칸에 반영된다. 이 병합은 **뼈대가 소유**(produce는
  "값 받음"만 봄) — 재개 봉투를 처음부터 union으로 설계해 후행 파괴 변경을 막는다.

## 설계

### A. 뼈대 vs 알맹이
```
ArtifactAgentBase (플랫폼 소유 — packages/agent)
├─ 수명주기: produce() 실행 → Artifact 검증 → sink 발사
├─ 상태·체크포인트: produce 진행 상태가 턴을 넘어 지속(승인 흐름과 같은 기계)
├─ 폼 프레임 기계: ctx.form()이 interrupt→프레임→제출→재개를 담당(자식은 값만 받음)
├─ 프리미티브(ctx): ask · form · rag · tool · extract   ← 전부 기존 권한 게이트 통과
└─ 싱크 디스패치: 1호 frame(플레이그라운드/JS 콜백 페이로드), 후속 api·ui-callback

자식(유저 정의 — 유일 구멍)
└─ async def produce(ctx) -> Artifact
```

### B. 프리미티브 (ctx — produce가 조립하는 부품)
| 프리미티브 | 하는 일 | 기존 기계 재사용 |
|---|---|---|
| `ctx.ask(text) -> str` | 유저에게 말하고 답 받기(턴 넘김) | interrupt/체크포인트 |
| `ctx.form(fields, prefill?) -> values` | 폼 프레임 띄우고 제출값 받기(**반복 호출 가능**) | 승인 프레임 일반화(kind 분기), 서버가 값∈후보 검증 |
| `ctx.rag(collection, query) -> hits` | 컬렉션 검색(엔티티 카탈로그 등) | search API + may_use_collection |
| `ctx.tool(name, args) -> result` | MCP 도구 호출(엔티티 성격 API 등) | 브로커 + agent_may_wire(113) + 승인 정책 |
| `ctx.extract(schema, text) -> dict` | LLM 구조화 추출(요소 분해 등) | 모델 설정·structured output |
- 프리미티브는 **닫힌 집합** — produce는 이 밖의 능력이 없다(뼈대가 보안 경계를 소유). 새 프리미티브
  추가 = 뼈대 스펙.

#### ctx.form의 이중 입력 기계 (뼈대 소유 — 사용자 강조 요구)
폼이 떠 있는 동안에도 채팅 입력은 닫히지 않는다. **재개 봉투를 처음부터 union으로**:
```
interrupt({kind:"form", fields, prefill, formId})
resume 봉투:  {type:"form", values}          ← 폼 제출(POST /chat/form/...)
           |  {type:"text", message}         ← 폼 대기 중 채팅 텍스트(기존 채팅 입구 그대로)
```
- `type:"text"` 처리(뼈대): pending 필드 대상 `extract` → 매칭 값을 프리필에 merge → **갱신된 프리필로
  폼 재제시**(활성 필수가 전부 차면 그대로 진행). 매칭 안 되는 텍스트는 일반 응답 후 폼 유지.
- produce는 이 분기를 모른다 — `values = await ctx.form(fields)` 하나로, 유저가 폼을 눌렀든 말로
  답했든 동일하게 최종 값을 받는다(알맹이마다 혼합 입력을 재구현하지 않게 뼈대가 소유).

### C. Artifact와 sink
- `Artifact = {kind: str, data: dict, raw?: str}` — produce의 반환. 뼈대가 (kind 존재·data dict)만
  구조 검증하고 프레임에 실음. 의미 검증은 produce 책임(자기 도메인이므로).
- sink(에이전트 설정): 1호 `frame` — `{artifact: {...}}` 프레임 emit, 플레이그라운드가 "임베드 시
  JS 콜백이 받을 JSON" 그대로 카드 렌더. 후속: `api`(SSRF·승인 재사용), `ui-callback`(임베드 SDK).
  싱크 추가는 프레임 소비자 추가일 뿐 — 에이전트·뼈대 무변경.

### D. 저작 경로 (알맹이를 유저가 어떻게 정의하나)
- 1호: **코드** — `register_agent(key, cls)` 레지스트리(스펙 085)에 ArtifactAgentBase 자식 등록,
  에이전트 생성 시 impl로 선택. **agent-flow 스킬(스펙 099)이 produce 코드젠 가능**(신뢰 등록 경로 기존).
- 에이전트 종류 3번째 **"산출물형"**(AGENT_TYPES: 직접 응답/조율형/산출물형).
- 후속(별도 스펙): 선언형 저작(관리자가 UI에서 파이프라인 조립) — 1호에서 프리미티브 계약이 굳은 뒤.

### E. 데모 2종 (둘째 구현으로 추상 무누수 측정 — 스펙 102 규율)
1. **targeting** (동적 폼 합성 — 사용자 시나리오 그대로):
   `extract(요소 분해) → 요소별 rag(카탈로그) → resolved별 tool(get_entity→후보) → form(합성 필드,
   프리필) → Artifact{kind:"targeting", data:{conditions:[{entity_id,label,value}]}}`.
   RAG 미매칭 요소는 폼 안내로 표면화(조용히 안 버림 — 스펙 125 원칙).
   시드: RAG 컬렉션 `targeting-entities`(구매이력·나이·거주지·성별, entity_id·동의어) + served MCP
   `targeting-catalog.get_entity`(구매이력=['최근','7일 전','최근 한 달'] 등).
2. **slot-fill** (정적 폼 — 대조 구현): 고정 필드 목록(예: 출장 신청)을 form 1~2회로 채움.
   동적 합성이 없는 최단 경로 — **두 구현이 같은 뼈대에서 갈라져야 추상이 안 샌 것**.

## RBAC/소유권 경계 (체크리스트 — 세션·RAG·도구 접촉)
- **입구 열거**: 신규 쓰기 입구는 폼 제출 `POST /chat/form/{session}/{formId}` 하나. 세션 소유자만
  (승인 `_may_resolve` 계열·404-fold), formId↔체크포인트 대응 검증(재개 위조 차단).
- 프리미티브가 유일한 능력 통로: rag=may_use_collection, tool=agent_may_wire+브로커 — **이 스펙이 여는
  새 권한 없음**. produce는 임의 HTTP/파일 접근 불가(프리미티브 닫힌 집합).
- ctx.form 제출값: 뼈대가 서버측에서 필드 명세 대조(값∈후보·타입) 후에만 produce에 전달.

## 검증 (완료 조건 — 측정 가능)
- **단위**: ctx.form 값 검증(후보 밖 거부)·Artifact 구조 검증·체크포인트 재개(중단 후 이어서).
- **통합(브라우저, mock LLM + 시드)**: 플레이그라운드 e2e ① targeting — 문장 입력→폼(4필드·후보·프리필)
  →수정·제출→artifact 카드(JSON) ② slot-fill — 폼 채움→artifact ③ **이중 입력** — 폼 대기 중 채팅으로
  "성별은 남성이야" 입력→폼 프리필 갱신 확인(핀). 승인 흐름 무회귀(kind 분기).
- **적대(codex)**: 후보 밖 값·타 세션 formId·미배선 컬렉션/도구 쓰는 produce·프리미티브 우회 시도.

## 단계
P1 뼈대+프리미티브(ask·extract·rag·tool — 폼 제외)+slot-fill 데모(대화만) /
P2 폼 프레임(kind 분기+UI+제출 API+union resume)+ctx.form+**이중 입력 병합**(텍스트→extract→merge→재제시) /
P3 targeting 데모(시드 카탈로그+동적 합성) — 둘째 구현 무누수 측정 /
P4 artifact 프레임+플그 카드+e2e+적대검증.

## 실행 결과
### P1 — 완료·검증 (2026-07-06)
- **`flows/artifact.py`**: `ArtifactAgentBase`(ABC — describe/build_graph @final, 구멍=produce) +
  `ProduceContext`(ask·extract·rag·tool; form은 P2 NotImplementedError) + `Artifact` + slot-fill 데모.
  `register_agent("artifact_slotfill", ...)` 등록(별도 구현체 — 기존 에이전트 코드 경로 무접촉).
- **핵심 기계 3개(설계 노트)**:
  1. **멀티턴 ask = interrupt 재실행 시맨틱**: 재개 시 produce 노드가 처음부터 재실행되고 interrupt()가
     기록된 답을 순서 매칭으로 반환(LangGraph 계약). 그래서 —
  2. **스텝 캐시(리플레이 결정성)**: extract/rag/tool 결과를 스레드별 호출순서 인덱스로 기록, 재실행은
     기록 반환(재호출 0 — 중복 부수효과·비용·비결정 LLM 재추출로 인한 리플레이 드리프트 차단.
     Temporal류 결정성 계약을 produce 문서에 명시). 프로세스 메모리·LRU 256(재시작 시 소실→read-only
     재실행 폴백 — 영속화는 후속).
  3. **세션 pending 포인터**: thread_id가 턴별 고유라(chat.py 설계) ask가 걸린 체크포인트는 이전 턴
     thread에 있다 → `_PENDING_ARTIFACT[session_id]={thread_id}`로 기억, 다음 입력이
     `Command(resume={"type":"text","message":...})`로 **그 thread를 재개**(승인의 Approval.checkpoint와
     같은 역할). union 봉투는 P2 form과 공유.
- **chat.py 분기(전부 kind 게이트 — 승인 경로 무접촉)**: ① interrupt kind=="ask" → 질문 텍스트 프레임
  +pending 등록+**정상 영속**(질문·답이 대화 이력에 남음 — 승인 턴의 "영속 안 함"과 다름) ② updates
  델타에 artifact 키가 있으면 요약 메시지+`{artifact:...}` 프레임 yield(노드 반환 AIMessage는 LLM 토큰
  스트림에 안 잡히는 것을 우회 — 산출물형에만 발화).
- **검증**: 단위 `verify_188_artifact.py` ALL PASS(멀티턴 ask 3왕복·**리플레이 캐시: produce 3회 실행에
  tool 정확히 1회**·빈 답 되물음 상한·Artifact 구조 검증·순수함수 6종) · e2e `verify-artifact-188.mjs`
  ALL PASS(플레이그라운드: 출장신청→목적지/기간/예산 3왕복→"산출물 완성 — travel-request" 요약+값 반영,
  pageerror 0) · 무회귀: scenario-audit 7/0 + verify_117 승인 흐름 ALL PASS.
- **경계(정직)**: pending 포인터는 프로세스 메모리(재시작 시 진행 중 produce 소실→새 실행 폴백),
  extract의 실모델 경로는 mock 미검증(P3 targeting에서 실검증), artifact 프레임은 emit만(플그 카드
  렌더는 P4).
