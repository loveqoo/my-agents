# Backlog — 작업 후보 보드 (AI 영역)

> Scaffolding의 **진입 재료**. "다음 뭐 하지?"에서 이 파일을 먼저 읽어 후보/완료/보류를 한눈에 본다
> (대화 재유도 대신 스캔). 굵은 단위(후보 작업)만 — 서브태스크는 안 쪼갠다(파편화 방지). learning/
> retrospect/spec의 `INDEX.md`가 회고 상기를 싸게 만들듯, 이 파일은 *백로그 상기*를 싸게 만든다.
> 규칙이 아니라 종이 한 장 — 새 작업 정해지면 여기서 옮기고, 끝나면 완료로 내린다.

## 후보 (다음에 할 만한 것) — 새 방향 4개(사용자 "모두 차례대로", 순서대로)

- ✅ **방향 1 — A2A 협업 실증 + 위임 승인 게이트**(스펙 117) 완료 → 아래 완료.
- ✅ **방향 2 — 관측·측정 계층(Langfuse)**(스펙 118) 완료 → 아래 완료.
- ✅ **방향 3 — 에이전트 평가 하네스(수치)**(스펙 119) 완료 → 아래 완료.
- **방향 4 — 저마찰 생성 성숙**(진행 예정) — 템플릿·복제·프리셋으로 에이전트 생성 저마찰화(UI/UX).

### 후속 씨앗 (급하지 않음)
- **다단 승인 큐**(스펙 116·117 OUT) — 다중 gated/A2A cap 순차 위임 시 두 번째 이후 interrupt를 chat.py
  resume 경로가 새 Approval row로 승격(현재는 고아, 안전은 fail-closed 유지). 101/102 다중 interrupt 완전성 갭.
- **A2A 승인 payload args 스냅샷 바인딩**(스펙 117 OUT) — "승인==전송"을 임의 브로커 호출자까지 일반보장
  (재개 간 args 비결정 대비). 기본 orchestrate 경로는 이미 안전.
- **a2a.delegate self-approve 시드**(스펙 117 OUT) — 현재 admin만 승인(fail-closed). 소유자 self-승인(105 선례).

## 진행 중

- (없음)

## 보류 / 후속 후보

- **능력 브로커 Phase 2 — memory 수정/삭제 + 인가 입도 강화** — Phase 2-a(MCP, 101)·2-b(RAG, 103)·2-c
  (memory **읽기**, 104)·memory **쓰기**(add, 105) 완료. 남은 후속: (a) ✅**memory 수정/삭제 능력=스펙 111 완료** — add(105)와 달리 **대상 mem_id 소유권 검증(053 `_assert_user_owns`)이 선행**(add는 자기 스코프
  생성이라 대상 없음, update/delete는 대상 행이 자기 것인지 확인 필요). 승인 게이트는 105 재사용. (b)
  per-cap·per-user 인가 + 에이전트 소유권(현재 Agent·Collection은 owner 없는 공유 카탈로그 → member에
  kind RBAC 주면 접근 가능한 allowlist 전부 호출 가능; codex 100/101 [P1] #1/#2 수용·명시경계. memory
  읽기/쓰기는 104/105가 principal-도출로 이 빚을 그 kind에 한해 갚음 — agent/mcp/rag는 여전히 공유). (c)
  카탈로그 커지면 벡터/하이브리드 검색(설계결정 10 — 현 rank_candidates는 lexical, 벡터는 OUT). (d) memwrite
  admin owner-only resolve/args 마스킹(codex 105 P2 미문서 경계 후속 — admin은 이미 053 접근이라 저위험).
- **데이터 채널 내부 attribution 강화** — 다중 위임 fold(102 `fold_results`)의 `## 능력:` 라벨은
  데이터 채널 *내부* 표식일 뿐 스푸핑 가능(신뢰 경계는 SystemMessage 격리로 견고, codex 102 설계한계).
  구조화 출력 등으로 내부 attribution 강화하는 후속.
- **노드 간 멱등 재개(선행 위임 결과 캐시)** — 다중 순차 위임 중 뒤 cap이 interrupt하면 재개 시
  delegate 노드가 처음부터 재실행 → 앞 read-only cap 재호출(gated 부수효과는 exactly-once라 안전하나
  관측상 중복, codex 102 [P1]). 다중 interrupt 난제(스펙 101/102 OUT)의 정공법 후속.

## 완료 (요약 — 상세는 각 스펙/회고)

- **에이전트 평가 하네스**(스펙 119, 방향 3) — 수치 자율(Ralph)의 전제인 결정적 통과율 수치를 내는
  개발·CI 하네스(tests/eval_harness.py: EvalCase·run_eval(cases,run_fn)→score·결정적 scorer trace_has/lacks·
  no_error·output_*). "조용한 초록"을 대죄로 규정→모든 경로 fail-closed. codex rung3 4구멍(빈 asserts
  자동통과·HTTP 실패 숨김·예외후계속 미검증·scorer 예외 전체중단) 봉합. 판별력 실측. 방향 3 완료
  (2026-07-02, 회고 100·learning 119).

- **관측·측정 계층 Langfuse**(스펙 118, 방향 2) — 기술스택엔 있으나 코드 0줄이던 Langfuse를 inert-until-
  configured로 배선(키 둘 다 있을 때만 활성·없으면 no-op·graceful·비파괴 config 병합). chat.py 3곳
  (메인·재개·로컬 A2A 서빙), langfuse v4 의존성(키가 스위치). codex rung3: [P2] with_trace 타입 구멍
  (callbacks list 가정)→타입별 접기+회귀가드. 전달 관통 검증(Recorder 콜백). 방향 2 완료(2026-07-02,
  회고 099·learning 118).

- **A2A 협업 실증 + 위임 승인 게이트**(스펙 117, 방향 1) — AgentProvider(kind=agent) 성공 협업을 채팅 1턴
  관통 실증(a2a_stream 결정적 패치: 원격 성공·1회 호출·질의 도달·종합) + approval_for opt-in 게이트
  (config.requires_approval 기본 off=무회귀·전송 이전 interrupt). codex rung3: requires_approval 스키마
  드롭(P1)→AgentConfig 필드+라운드트립 가드, 승인==전송 재개 경계(P1)→문서화, 비-dict config(P2)→방어.
  방향 1 완료(2026-07-02, 회고 098·learning 117).

- **재개 시 선행 위임 결과 보존**(스펙 116, 102 codex [P1] 봉합) — 다중 순차 위임 중 뒤 gated cap
  interrupt 시 재개서 앞 read-only cap 재호출되던 것을, cap 하나씩 delegate self-loop(pending/done
  operator.add)로 소비해 재개 멱등화(cap 하나=체크포인트 경계). codex [P1] 첫 cap 재-discover→plan
  노드 분리로 봉합. 다중 gated 승인 표면화는 OUT(안전 fail-closed 유지). "1~4 루프" 4번(마지막) 완료
  (2026-07-02, 회고 097·learning 116).

- **위임 결과 attribution 견고화**(스펙 115, 102 codex 설계한계 봉합) — 다중 위임 fold의 `## 능력:` 라벨
  스푸핑을 요청별 랜덤 nonce 펜스(⟦BEGIN nonce⟧…⟦END nonce⟧, 라벨은 펜스 밖·nonce는 위임 능력 미노출)로
  위조 불가화. codex rung3: 라벨 자체 위조(cap.name 자원명, P1)→_label_safe 정규화, 단일 raw+지침 불일치
  (P2)→단일도 펜스+지침 조건화. 3런+102 무회귀. 사용자 "1~4 루프"의 3번 완료(2026-07-02, 회고 096·learning 115).

- **화면에 주인 표시 + 비소유 관리 버튼 숨김**(스펙 114) — 112 백엔드 게이트를 UI에 반영. 백엔드가
  owner_id·can_manage를 Out에 실어 내리고(may_manage=assert의 불리언 형제) 프론트는 OwnerTag+버튼
  가드. 브라우저 검증이 놓친 렌더 지점(목록 행 삭제) 포착·수정. verify_114+tsc+shot-owner-114.
  사용자 "1~4 루프"의 2번 완료(2026-07-02, 회고 095·learning 114).

- **런타임 tool 배선 인가**(스펙 113, 112 P0 봉합) — 채팅 런타임이 config mcps/vectorTables 이름으로
  크레덴셜 tool 배선하던 무인가 경로에 인가. 주체=에이전트 **작성자**(채팅 사용자 아님—공유 보존),
  단일 헬퍼 agent_may_wire(NULL-owner 무회귀·특권·자기소유·published·RBAC per-cap). codex rung3:
  override 주입 confused-deputy(P0)→저장본=작성자·주입분=호출자 분리, non-UUID owner casbin 충돌(P2)→
  UUID 선검증. 3런+무회귀. 사용자 "1~4 루프"의 1번 완료(2026-07-02, 회고 094·learning 113).

- **공유 카탈로그 소유권 + per-cap 인가**(스펙 112) — 브로커 인가를 kind→per-cap(`capability:{kind}:{name}`)
  으로 좁히고(축 A, 인가 빚 상환), Agent·McpServer·Collection에 owner_id 붙여 카탈로그 **관리(수정/삭제)**를
  소유자/특권 게이트(축 B). **설계 갈래**=소유권으로 invoke 막으면 공유 에이전트 깨짐→소유권=관리만·사용은
  per-cap RBAC. 게이트 추가가 기존 열린 문(카탈로그 변경 인증만) 봉합. codex rung3: 메모리 3라우트·404-fold
  body·mcp 서버단위 봉합, P0(런타임 tool 배선 우회)는 정직히 OUT→후보로 승격. 백로그 #1의 (b) 완료
  (2026-07-02, 회고 093·learning 112).

- **브로커 메모리 수정/삭제 능력**(스펙 111) — 브로커가 사용자 기억을 수정/삭제(memedit). 대상 mem_id 소유권 선행(남의 기억 못 건드림, 미소유=404-fold)+실행 전 승인(삭제 비가역→관리자만 fail-closed)+principal user_id 고정(anti-leak). 소유권 술어 `memory.user_owns` HTTP와 단일화. 검증 3런(단위+그래프+실mem0)+codex 적대(하중가정 정직화). 백로그 #1의 (a) 완료(2026-07-02, 회고 092·learning 111).

- **엔드투엔드 오케스트레이션 시연**(스펙 110, 106 잔여) — 조율형 에이전트로 채팅 1턴을 돌려 브로커가 실제로 일을 넘기는지 trace의 `broker_invoke:rag:docs_kb` 노드로 확인. 결정적 테스트(verify_110 5/5)+플레이그라운드 인스펙터 스샷. **발견**: 위임은 유저 세션에서만(머신 토큰 deny-by-default)—E2E는 실제 principal 재현 필요(2026-07-02, 회고 091·learning 110).

- **폼 3단계 + 재사용 효율 피커**(스펙 109) — 등록 폼을 기본/하는 일(종류별)/세부설정(접힘) 3단계로, 늘어나는 항목은 재사용 `PickerGroups`(접이식+검색+카운트)로 효율 렌더, **같은 개선을 플레이그라운드 오버라이드에도** 일관 적용(어댑터로 이질 저장 흡수·storage 무변경). 브라우저 등록폼 9/9+오버라이드 6/6(2026-07-02, 회고 090·learning 109).

- **에이전트 폼 유저언어 재구성**(스펙 108) — 106·107 능력 UI를 사용자 세번째 지적(impl 내부어·MCP 두곳 중복·전략어 어려움) 후 뿌리수술: 유저언어(에이전트 종류=직접응답/조율형, 무엇에 맡길까요?)+**종류가 설정면 가름**(직접응답=직접자원칸, 조율형=위임칸만→MCP 한곳 중복소멸). 브라우저 9/9(내부어·기술id 부재 innerText 자동단언)(2026-07-02, 회고 089·learning 108).

- **능력 브로커 UI**(스펙 106) — 편집 폼에 실행 방식(impl) Select + 능력(capabilities) kind별 피커
  추가 → 브로커(100–105 6 provider)를 UI 저작으로 개방. `GET /agent-impls`(레지스트리 drift0)+AgentOut
  capabilities 직렬화; 능력 피커는 cap id `<kind>:<name>` 규약이라 폼이 이미 가진 데이터서 순수 포매팅
  조립(새 카탈로그 EP 불요). 브라우저 10런+왕복+엔드포인트 검증(2026-07-02, 회고 087·learning 106).
  **백로그 2항목(impl 노출·capabilities 편집 Phase 2-d) 동시 소진.**

- **로드맵 12항목**(스펙 033, 034~042) — 2026-06-27 소진.
- **제안 8항목** — #1 conformance(089)·#2 입력히스토리(091)·#3 도구원본숨김(092)·#5 MCP/RAG삭제
  차단(093)·#6 오버플로(095)·#7 메모리검색UI일관(097)·#8 세션검색(098).
- **#4 트리노드 그래프빌더** — 폐기 후 스펙 099(agent-flow 스킬 코드젠, 데모 `route`)로 대체 해결
  (2026-07-01, 회고 080·learning 099).
- **능력 브로커 Phase 1**(스펙 100) — discovery 시임(discover/describe/invoke)+정책 게이트(allowlist∩
  RBAC deny-by-default)+A2A provider+데모 `orchestrate`(서브스텝 조립) 완료(2026-07-01, 회고 081·
  learning 100). codex 3런: #3(untrusted 데이터 채널 격리) 수정, #1/#2(인가 입도) 명시경계로 문서화.
- **능력 브로커 Phase 2-a**(스펙 101) — MCP provider(툴 단위 `mcp:<server>/<tool>`, provider 시임으로
  정책·메커닉 분리) + 서브스텝 HIL(위임 MCP 툴 승인요구 → 전송이전 interrupt, 기존 Approval/resume
  재사용) 완료(2026-07-01, 회고 082·learning 101). integration rung이 설정 지속경로 누락
  (`AgentConfig.capabilities` 필드) 포착·수정. codex 0 actionable(#3 오탐 기각, #1/#2 기존 명시경계).
- **능력 브로커 Phase 2-b**(스펙 103) — RAG provider(kind=rag, `rag:<collection_name>`, 첫 **읽기전용**
  provider). 셋째 provider가 시임 무누수를 재측정(`_permitted` rag 분기 0줄=정책은 정말 provider와 분리).
  invoke는 `search_collections` 코어 재사용+`format_rag_hits` 추출로 엔드포인트·인챗도구·브로커 **세 입구
  한 코어**(drift 0). 읽기전용→`approval_for` 항상 None(정책은 완전 적용=**두 게이트 분리**) 완료
  (2026-07-01, 회고 084·learning 103). 46 ok + 072/100/101/102 무회귀. codex 3판정: [P1]인챗도구
  vectorTables=브로커 밖=정직한 경계(다른 신뢰모델)→스펙 OUT+H4/H5 안전불변식, [P2]질의무제한→공유코어
  4000자 상한, [P2]빈이름 `rag:`→파싱층 방어.
- **능력 브로커 Phase 2-c**(스펙 104) — Memory provider(kind=memory, `memory:user`, 첫 **per-user 소유**
  능력). 100/081이 미룬 **인가 입도 빚 상환**: 공유카탈로그와 반대로 능력 이름에 대상 안 박고 소유자를
  **런타임 principal서 도출**(user_id=`str(principal.id)`, invoke 스코프 오직 `{"user_id":self._user_id}`)
  →이름으로 남 못 가리켜 교차유출 *구조적* 불가+어드민 에스컬레이션 자동차단. 정책 무변경(`_permitted`
  memory분기 0), invoke=`recall_probe` 코어+`format_memory_hits` 추출 공유(drift 0), 읽기전용→approval None.
  완료(2026-07-02, 회고 085·learning 104). verify_104 3런(FakeMem 결정적격리+실 mem0 통합)+084/100/101/102/
  103 무회귀. codex 3판정 P0/P1 없음: [P2]limit 타입미검증→recall_probe clamp, [P2]승인재개 브로커 user_id
  누락→주입(새 상태축=모든 팩토리), [P2]format_memory_hits=격리아님→docstring+비목표 명시.
- **능력 브로커 Memory write**(스펙 105) — Memory write provider(kind=memwrite, `memwrite:user`, **첫
  부수효과·승인 게이트 능력**). 두 방어 겹침: ①쓰기 축=user_id(자기)만·principal 바인딩(104, agent_id 금지
  =051 누출축) ②승인 게이트(031 처방—프롬프트 아닌 구조)=`approval_for` 항상 non-None, memory.add 이전
  interrupt→승인돼야 저장(reject 무저장/approve 1회). 읽기≠쓰기 별도권한(memwrite kind), **소유자 self-승인
  기본**(사용자 결정—member memory.write self_approve 시드, data.delete는 admin 유지), infer=False(승인=저장).
  완료(2026-07-02, 회고 086·learning 105). verify_105 3런(FakeMemAdd+**최소 1노드 graph 승인왕복 LLM불요**+
  실 mem0 쓰기→읽기 왕복)+066/084/100-104 무회귀. codex 3판정 P0/P1 없음: [P2]길이무제한→공유헬퍼 4000자
  (승인한것==저장되는것), [P2]admin 승인열람=053으로 이미 접근(권한델타0)→명시화.
- **전략 교체형 오케스트레이션**(스펙 102) — 브로커 위 오케스트레이션 방식을 **소유자가 고르는 전략**
  으로: 공통 조상 ABC 템플릿(OrchestrationAgentBase가 골격·채널격리·HIL·정책 소유, 자식 유일구멍=
  `select`) + 첫 출하 2전략(FirstMatch[행위보존]·Ranked[결정적 top-k], 둘째구현으로 추상 무누수 측정) +
  agent-flow 스킬 전략 분기(D7) 완료(2026-07-01, 회고 083·learning 102). 40 ok + 무회귀. codex 5건 정직
  분류: [P1]다중위임+중간interrupt 재실행=여집합공격성공이나 안전위반 아님→주석경계+H10 실측(정직화),
  [P2]override홀→@final, [P2]select계약→chosen⊆candidates 교집합, [설계한계]라벨스푸핑→명시, ABC=오탐.
