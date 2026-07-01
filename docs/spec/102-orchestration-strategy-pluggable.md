# 102 — Discovery 오케스트레이션: 전략 교체형 골격 (공통 조상 + 첫 출하 2전략)

## 배경·목적

능력 브로커(스펙 100·101)는 `discover/describe/invoke` 한 시임과 견고한 정책 게이트를 갖췄다.
그러나 데모 `orchestrate` 플로우는 **`discover(query, limit=1)` → 첫 후보 하나만 위임**한다 — 즉
"단일 위임"이지 "오케스트레이션"이 아니다. 후보 선택은 **lexical 부분일치 첫 매치**뿐이다.

이 스펙은 브로커 **위**에 **전략 교체형 오케스트레이션 골격**을 얹는다. 오케스트레이션 방식(후보를
어떻게 고르고 몇 개를 조합하나)은 플랫폼이 하나로 못 박지 않고 **에이전트 소유자가 고르는 전략**으로
노출한다. 이 저장소의 근본 가치(저마찰 생성·재사용·다양한 에이전트)와 맞다.

## 현재 상태 (gap)

- `packages/agent/src/agent/flows/orchestrate.py` — `OrchestrateAgent`: analyze→delegate→synthesize.
  `delegate`가 `discover(limit=1)` 후 `caps[0]`만 invoke. 채널 격리(`build_synthesis_messages`,
  스펙 100)와 서브스텝 HIL(스펙 101)은 이미 있음.
- `broker.discover(query, limit=5)` — provider 후보 수집 후 lexical 부분일치 필터, 앞 `limit`개 반환.
  랭킹(relevance 점수) 없음.
- 공통 조상은 `CustomAgent` **Protocol**(런타임 `runtime.py`)로 존재하나 *구조적*이라 **골격(구현)을
  담지 못함**. 각 flow가 describe/build_graph를 독립 구현.

## 설계 결정

### D1. 전략 = 각각의 impl (플로우 안 `if` 아님)

분기는 **"어떤 클래스를 고르나"** 한 지점(런타임의 impl 레지스트리 조회)으로 몰고, 플로우 안엔 전략
분기를 두지 않는다. 새 config 필드를 만들지 않고 **이미 배선된 `config["impl"]` 키를 재사용**한다
(스펙 088의 "새 필드는 모든 입구서 다뤄질 때까지 dead" 함정 회피). 유저는 impl 값으로 전략을 고른다.

### D2. 공통 조상 = 추상 기반 클래스(ABC) + 템플릿 메서드

소유자 요구("나뉜 클래스는 공통 조상을 갖는다")를 정확히 만족하는 형태:

```
OrchestrationAgentBase(ABC)                     ← 조상: 골격·불변식 소유
  describe(): AgentManifest                      → supports_hil 등 정직 선언
  build_graph(ctx): analyze → delegate → synthesize  ← 골격(구현, 드리프트 0)
    · analyze   = 결정적 검색어 추출(모델 없음, 기존 재사용)
    · delegate  = candidates=discover(N); chosen=self.select(q,candidates);
                  for c in chosen: invoke(c) → 결과를 **데이터 채널**로 fold
    · synthesize= build_synthesis_messages(persona, delegated, msgs)  ← 채널 격리(스펙 100)
  @abstractmethod select(query, candidates) -> list[Capability]   ← 자식이 채우는 **유일한 구멍**
  ├─ FirstMatchOrchestrateAgent : select = candidates[:1]        ← 현재 동작(행위보존)
  └─ RankedOrchestrateAgent     : select = rank_candidates(q,candidates)[:k]  ← 전략 A(신규)
```

- 불변식(브로커 정책 재검증·deny-by-default·채널 격리·HIL)은 **조상 한 곳**에 산다 → 드리프트 0
  (RBAC 체크리스트 §3 "단일 헬퍼"). 자식은 상속으로 강제되어 채널 격리·HIL을 **뺄 수 없다**.
- 조상이 `describe`/`build_graph`를 구현하므로 `CustomAgent` Protocol에 **자동 적합** → 자식 전부
  적합(스펙 089 conformance 무회귀, `get_agent_impl`의 isinstance 게이트 통과).

### D3. `select` 정책은 모듈 순수함수

`RankedOrchestrateAgent.select`는 모듈 순수함수 `rank_candidates(query, candidates)`에 위임한다
(스펙 099 규약: 분기·판정 로직을 노드 클로저 밖 순수함수로 빼야 **실LLM 없이 결정성 단언**). 랭킹:

- 점수 = `query` 토큰과 후보 `name + id + hook`(소문자) 토큰의 **겹침 수**(결정적).
- 동점 tie-break = `id` 사전순(안정). 겹침 0 후보는 결과에서 제외(deny-by-default 정신).
- 빈 query → 원래 순서 유지(후보 population은 이미 브로커가 스코프).

### D4. 첫 출하에 전략을 **둘** 낸다 (추상화 무누수를 *측정*)

참고 자산 039/085: 조상 추상화를 만들며 전략을 하나만 내면 "조상이 안 샌다"가 **주장에 그친다**(구현
1개엔 딱 맞게 만들어짐). 무누수는 **둘째 구현으로 측정**된다. 그래서:

1. 현재 `OrchestrateAgent`를 조상 밑 `FirstMatchOrchestrateAgent`로 **행위보존 리팩터**
   (스펙 101 AgentProvider 방식). impl 키 `orchestrate`는 **그대로 FirstMatch를 가리켜** 기존
   에이전트 무영향(레지스트리 레벨 행위보존).
2. 신규 `RankedOrchestrateAgent` = impl 키 `orchestrate-ranked` 추가.

얻는 것: (a) 두 자식으로 조상 추상화 *측정*, (b) 현재 동작 회귀 게이트 보존, (c) 유저가 첫날부터 진짜
전략 선택지(`orchestrate` vs `orchestrate-ranked`).

### D5. 다중 위임은 **순차** fold (첫 컷)

`RankedOrchestrateAgent`는 상위 k(기본 3, 클래스 상수)를 **순차** 위임하고 각 untrusted 결과를 라벨
붙여 **데이터 채널 하나에 fold**(모든 결과가 Human 블록, system엔 절대 안 감 — 스펙 100 격리 유지).
순차인 이유: 병렬+interrupt(HIL)+멱등은 별개 난제(스펙 101 OUT "다중 interrupt"). 순차는 각 invoke가
스펙 101 HIL 시맨틱(interrupt-before-sideeffect)을 그대로 보존해 측정 가능. **진짜 병렬은 후속.**

### D6. 신뢰 등록 = 스펙 099 방식 재사용

두 자식을 `runtime._bootstrap_builtins`에 신뢰 등록(late-import + `register_agent` 2줄, 런타임 eval
없음 — 스펙 085 U5·099 보존). UI(SPA 편집 폼)의 impl 드롭다운 노출은 백로그의 별도 항목(085 H5 갭)과
동일 작업 → **이 스펙 비목표**, 후속.

### D7. `agent-flow` 스킬에 오케스트레이션 전략 분기 추가

향후 전략(B 플래너·C 반복)도 **조상의 자식으로** 저작되어야 골격·불변식이 상속되고 스킬이 `select`
**정책만** 생성한다("자식이 채널격리·HIL을 뺄 수 없다"를 *저작 시점*에도 강제). `.claude/skills/
agent-flow/SKILL.md`에 분기를 넣는다:

- **1. 의도 수집** 첫 질문 추가 — "이 플로우가 **오케스트레이션 전략**인가(브로커로 능력 발견·조합)?"
  - 아니오 → 기존 경로(`route.py` 템플릿, CustomAgent 처음부터).
  - 예 → 오케스트레이션 전략 경로(아래).
- **2. 모듈 생성**(전략 경로) — 템플릿을 `orchestrate_ranked.py`로, **`OrchestrationAgentBase`를 상속**
  하고 `@abstractmethod select(query, candidates)`만 구현. `build_graph`/`describe`/채널격리/HIL은
  **작성 금지**(조상 소유 — 재작성하면 드리프트). `select` 정책은 모듈 순수함수(`rank_candidates`류).
- **3. 등록** — 동일(2줄).
- **4. 검증** — `verify_102`를 템플릿으로 `select` 결정성·골격 드리프트0(조상 노드집합)·채널격리 상속·
  conformance. 조상 불변식은 조상 테스트가 커버하므로 자식 테스트는 `select`만.
- **수용 게이트**에 "자식이 `build_graph`/`describe`를 **재정의하지 않았나**"(override 홀 없음) 추가.

스킬 파일 자체(`.claude/skills/`)는 codex 금지 경로라 codex 검토 대상이 아니다 — 스킬이 가리키는
**생성 산출물**(packages/agent/flows/)만 codex가 본다. 스킬 정확성은 *이 스펙이 손으로 만든 2전략이
스킬이 생성했을 형태와 일치*함으로 측정된다(템플릿 소스 = 실제 출하 파일).

## RBAC/소유권 경계 체크리스트 — 상속으로 만족(재논증 아님)

이 스펙은 **유저 데이터에 새 입구를 추가하지 않는다.** 소유권 판정은 전적으로 `broker.invoke`(스펙
100·101)가 소유하며, 조상이 그 invoke를 호출한다 → 전략 자식은 정책을 **건드릴 수 없다**(상속 강제).
따라서 체크리스트는 *상속으로 만족*되고 여기서 재논증하지 않는다. 유일하게 새로운 표면은 **다중 결과
fold**인데, 이는 채널 격리(모든 untrusted 결과가 데이터 채널)로 방어되며 U-검증에서 단언한다.

## 완료 조건 (측정 가능 — 3런 검증 사다리)

**verify_102_orchestration_strategy.py**

- **[U] 단위(순수, 실LLM 없음)**:
  1. `rank_candidates` — 점수/순서 결정성(더 겹치는 후보가 앞), 동점 id 사전순 tie-break, 겹침 0 제외,
     빈 query 원순서.
  2. `FirstMatch.select`가 `candidates[:1]`, `Ranked.select`가 `rank_candidates(...)[:k]`.
  3. 골격 드리프트 0 — 두 자식의 `build_graph` 노드 집합 = {analyze, delegate, synthesize} 동일
     (같은 조상 메서드).
  4. 채널 격리 — 다중 fold 결과가 `build_synthesis_messages`에서 **Human에만**, system엔 지침만
     (스펙 100 단언 재사용, k개 결과 버전).
  5. conformance — 두 자식 `isinstance(CustomAgent)` → `classify_runtime` conforming(스펙 089).
- **[H] 통합(실 브로커 + 실 DB)**:
  6. Ranked가 **덜 관련된 후보보다 더 관련된 후보를 선택**(실 discover 후보로 결정적 pick 단언).
  7. 다중 위임 — 상위 k가 k개 untrusted 결과를 데이터 채널로 fold, 실 노드 타임라인에 다중
     broker_invoke.
  8. HIL 보존 — Ranked가 고른 승인요구 MCP 툴이 여전히 interrupt(스펙 101: pre=0/approve=1).
  9. FirstMatch = 현재 `orchestrate` 동작 재현(행위보존) → **verify_100/101 무회귀**.
- **[A] 적대(codex)**: "보장 목록의 여집합" — 자식이 채널 격리·정책을 우회할 구멍(override 홀)이
  없나, ABC가 실제로 강제하나(abstractmethod 미구현 시 인스턴스화 실패). 파일시스템 경계 프리픽스
  적용(.claude/skills 등 제외, 코드 파일만). no P0/P1.

## 비목표 (OUT)

- 진짜 병렬 위임(순차 fold의 후속) · 다중 interrupt 한 턴 처리(스펙 101 OUT 연장).
- 모델 플래너(전략 B)·반복 루프(전략 C) — 같은 조상 밑 후속 자식으로 추가.
- top-k의 k를 config로 노출 · admin UI impl 드롭다운 노출(085 H5, 별도).
- 벡터/하이브리드 검색(설계결정 10) — 랭킹은 lexical 결정적으로 시작.
- per-cap·per-user 인가·에이전트 소유권(스펙 100/101 §명시 경계 유지).
