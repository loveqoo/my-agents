# 294 — 브로커 provider 조립 분리: 소비자는 추상만, 조립은 한 곳에

## 배경

사용자 지적(2026-07-11): "구조가 있으면 상세를 감춰야 추상의 아름다움·의존의 단순함·테스트
편의가 따라온다. 인터페이스는 강한 규약이면서 DI로 유연 조립도 된다. 구현에 최적화하면 예측이
어렵다." **구조 우선 = 예측 가능성 = 경계 = 그 자체가 스펙.**

실측으로 확인된 유일·정확한 위반: **`PolicyScopedBroker.__init__`(core.py:98-105)가 6개 구체
provider 클래스와 각자의 생성자 배선을 직접 안다.** broker의 본래 책임은 "정책 스코프 + kind
디스패치"(소비)인데 거기에 "누가 존재하고 어떻게 만드는가"(조립)가 섞였다.

같은 코드베이스가 **이미 이 은닉을 두 군데서** 한다 — provider만 예외:

| 서브시스템 | 생성 은닉 | 소비자가 구체를 아나 |
|---|---|---|
| agent | `_REGISTRY` + `get_agent_impl`(runtime.py) | ❌ 키로 조회 |
| memory backend | `_BACKENDS` + `resolve_backend`(memory/backend.py) | ❌ 설정으로 해소 |
| **provider** | **없음 — broker가 직접 생성** | ✅ **6개 다 안다** |

증거 보강: broker는 `self._session_factory`를 **저장만 하고 한 번도 안 읽는다**(grep 1건=대입뿐).
자기가 안 쓰는 DB 팩토리를 쥔 것 = 조립 관심사가 소비자로 샌 증상.

깨지는 이득(사용자 3항목에 매핑):
- **추상의 아름다움**: broker가 "조립+소비" 두 책임 겸함. 순수 소비자는 `list[_CapabilityProvider]`를 받기만.
- **의존의 단순함**: `__init__`이 6개 구체 import·배선 → 7번째 provider = broker 수정(개방-폐쇄 위반).
- **테스트 편의**: provider 집합을 못 갈아끼움(broker가 스스로 생성) → 가짜 provider로 디스패치·정책만
  격리 테스트 불가.

## 목표 (측정 가능)

1. **`PolicyScopedBroker`는 `_CapabilityProvider` 추상에만 의존** — `__init__`이 provider를 **주입받는다**
   (`providers: list[_CapabilityProvider]`). core.py에서 구체 provider 클래스 import·생성 **0건**.
   - 측정: `grep -c "AgentProvider(\|McpProvider(\|RagProvider(\|MemoryProvider(\|MemoryWriteProvider(\|MemEditProvider("` in core.py **PolicyScopedBroker 본문 = 0**.
   - 측정: broker `__init__` 내부에 `Provider(` 호출 **0건**. `self._session_factory`(사용처 0) **삭제**.
2. **조립을 한 함수로** — `build_providers(ctx: BrokerContext) -> list[_CapabilityProvider]` 신설
   (broker/ 하위, 예: `broker/composition.py` 또는 `broker/providers/__init__.py`). 구체 6개를 아는
   **유일한 곳.** 두 호출부(`build_broker` core.py:295, `chat_approval.py:133`)가 이걸 경유.
3. **`BrokerContext` 타입 = provider 생성 규약** — provider 조립 표면을 한 데이터 타입으로 명문화
   (dataclass 권장): `session_factory`, `principal`, `user_id`, `delegation_chain`, `delegation_budget`,
   `rag_min_scores`. 이 타입이 "provider를 만들려면 무엇이 필요한가"의 단일 계약(경계=스펙).
4. **행위 보존** — 관측 동작(Capability·InvokeResult·승인 payload·node_label·디스패치 결과) 바이트 동일.
   재수출 계약(`vars(api.broker)` 여집합 0). verify_104/105/111 + 실모델 스위트 51/51 + `make metrics` 전판.
5. **새 테스트 seam 실증** — 가짜 `_CapabilityProvider` 리스트를 broker에 주입해 디스패치·`_permitted`가
   구체 없이 동작함을 단언하는 단위 테스트 1개(추상 의존을 *증명*).

## 설계

### 경계(옮길 것 / 남길 것) — 실측 확정
- **broker-레벨(남김, 소비/정책)**: `allowlist`, `rbac_allows`, `tool_policy`. (`session_factory`는
  사용처 0 → 삭제.)
- **provider-레벨(옮김, 조립)**: `session_factory`(6개), `principal`·`delegation_chain`·
  `delegation_budget`(Agent), `rag_min_scores`(Rag), `user_id`(Memory×3) → `BrokerContext`로.

### build_providers
```python
@dataclass(frozen=True)
class BrokerContext:
    session_factory: async_sessionmaker[AsyncSession]
    principal: User | str | None
    user_id: str | None
    delegation_chain: tuple = ()
    delegation_budget: dict | None = None
    rag_min_scores: dict | None = None

def build_providers(ctx: BrokerContext) -> list[_CapabilityProvider]:
    return [
        AgentProvider(ctx.session_factory, ctx.principal, ctx.delegation_chain, ctx.delegation_budget),
        McpProvider(ctx.session_factory),
        RagProvider(ctx.session_factory, ctx.rag_min_scores),
        MemoryProvider(ctx.session_factory, ctx.user_id),
        MemoryWriteProvider(ctx.session_factory, ctx.user_id),
        MemEditProvider(ctx.session_factory, ctx.user_id),
    ]
```
broker `__init__`은 `providers`를 받아 `self._providers = providers` + `self._by_kind = {p.kind: p}`만.

### 결정: 조립 함수 O, 런타임 가변 레지스트리 X (권장·검토 요청)
agent는 `_REGISTRY`+`register_agent`(가변)인데 provider는 **왜 함수인가**: agent는 사용자
플러그인(agent-flow 스킬이 코드젠·등록)이라 런타임 개방이 *요구사항*. provider는 **플랫폼 내부
고정 집합**(스펙 동반으로만 증감) — 가변 레지스트리는 그 구동자가 없어 패턴만 흉내(카고컬트).
개방-폐쇄는 "조립 함수 한 줄 추가(broker 무변경)"로 이미 충족. **구조는 잡되 기계는 최소** =
지금 필요한 만큼의 구조. *새 능력 소스가 런타임 플러그인이 되는 날 레지스트리로 승격*(그 땐 driver 존재).
→ 이 선택만 검토 확인 요망(가변 레지스트리를 원하면 그 형태로 변경).

### 두 호출부
`build_broker`(core.py)·chat_approval의 빌더가 각자 rbac_allows 클로저·uid 도출 후 `BrokerContext`
조립 → `build_providers(ctx)` → `PolicyScopedBroker(allowlist, rbac_allows, providers, tool_policy)`.
현재 두 곳이 구체 배선을 각자 알 필요가 사라져 **중복 소멸**.

## 검증 (RBAC 경계 체크리스트 트리거 — user_id/principal/delegation 관통)

1. **입구 열거**: broker 생성 입구는 닫힌 2개(`build_broker`, `chat_approval`). 둘 다 `build_providers`
   경유로 통일(누락 입구 = provider 배선 드리프트 → 회귀). 제3 입구 없음(grep로 재확인).
2. **불변식 물리 보존**:
   - **anti-leak**: `user_id`는 `BrokerContext.user_id`(principal 도출값)로만 provider에 도달 —
     cap_id·args 경로 **여전히 없음**. Memory 3형제 생성 인자 무변경(user_id만).
   - **승인 게이트·소유권 선행**: provider `invoke`/`approval_for` 본문 무변경(조립만 이동).
   - **delegation 관통**: `delegation_chain`·`delegation_budget`이 AgentProvider까지 그대로(순환·깊이 게이트 보존).
3. **단일 헬퍼**: `build_providers` = provider 배선 단일 출처(드리프트 0).
4. **검증 사다리 3런(비겹침)**:
   - ① 단위: 가짜 provider 주입 디스패치 + `BrokerContext`→`build_providers` 6개·kind 정확 매핑.
   - ② 실인프라 통합: verify_104(read)·105(write)·111(edit) + 스위트 51/51(seed+restart).
   - ③ 적대(codex): 행위 보존 여집합 — 주입화가 (a) 교차 축 여는 틈(user_id 오배선), (b) tool_policy
     MCP 오버라이드 경로 단절, (c) delegation 게이트 우회, (d) 재수출 심볼 소실을 만드는가.
5. **자가-잠금 핀**: 정당한 본인 접근(자기 memory·자기 위임 재개)이 주입 경로에서도 살아있나 —
   chat_approval 재개 경로 verify_104 P2 케이스로 확인.

## OUT (감출 것과 드러낼 것의 경계 — 억지 추상 금지)
- **신뢰 경계 파싱은 명시 유지**: cap_id 문법(`_kind_of`/`_parse_*`)·`if source ==`·외부 JSON
  `isinstance`는 *우리 타입 계층 밖 외부 데이터* 방어 파싱 → 다형성으로 감추면 억지(스펙 293 C 결론 유지).
- **런타임 가변 provider 레지스트리 금지**(위 결정) — 플러그인 요구 생기면 별도 스펙.
- **잎 provider 생성자 다양성 보존** — Agent/Rag/Memory가 각자 다른 인자를 받는 건 결함 아니라 좋은 DI
  (각자 필요한 것만). 통일 강제 금지.
- `_CapabilityProvider` Protocol 자체·provider 내부 로직·`_by_kind` 디스패치 알고리즘 무변경.
