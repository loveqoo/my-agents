# Backlog — 작업 후보 보드 (AI 영역)

> Scaffolding의 **진입 재료**. "다음 뭐 하지?"에서 이 파일을 먼저 읽어 후보/완료/보류를 한눈에 본다
> (대화 재유도 대신 스캔). 굵은 단위(후보 작업)만 — 서브태스크는 안 쪼갠다(파편화 방지). learning/
> retrospect/spec의 `INDEX.md`가 회고 상기를 싸게 만들듯, 이 파일은 *백로그 상기*를 싸게 만든다.
> 규칙이 아니라 종이 한 장 — 새 작업 정해지면 여기서 옮기고, 끝나면 완료로 내린다.

## 후보 (다음에 할 만한 것)

- (없음 — 다음은 Scaffolding서 새 방향 모색)

## 진행 중

- (없음)

## 보류 / 후속 후보

- **admin UI에서 impl 선택 노출** — 생성된 flow(스펙 099 `route`·102 `orchestrate`/`orchestrate_ranked`
  등)를 SPA 편집 폼 드롭다운에서 고르게. 현재 편집 폼은 `impl`을 안 보냄(085 H5 갭). 스펙 099 §5·102
  OUT로 남긴 후속. **전략 교체(102)가 나오며 노출 가치↑**(사용자가 오케스트레이션 전략을 UI로 선택).
- **능력 브로커 Phase 2 — memory 수정/삭제 + 인가 입도 강화** — Phase 2-a(MCP, 101)·2-b(RAG, 103)·2-c
  (memory **읽기**, 104)·memory **쓰기**(add, 105) 완료. 남은 후속: (a) **memory 수정(update)/삭제(delete)
  능력** — add(105)와 달리 **대상 mem_id 소유권 검증(053 `_assert_user_owns`)이 선행**(add는 자기 스코프
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
- **admin UI에서 capabilities allowlist 편집(Phase 2-d)** — 에이전트 config `capabilities`를 SPA서
  편집. **지속 경로는 이제 열림**(스펙 101에서 `AgentConfig.capabilities` 필드 추가) → UI 폼만 남음.

## 완료 (요약 — 상세는 각 스펙/회고)

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
