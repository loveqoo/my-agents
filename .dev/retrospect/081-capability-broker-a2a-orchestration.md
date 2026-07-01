# 081 — 능력 브로커 Phase 1 + A2A 오케스트레이션(서브스텝)

지배 스펙: `docs/spec/100-capability-broker-a2a-orchestration.md`
관련 자산: 설계노트 `.dev/a2a-capability-broker-design-notes.md`(결정 10개), learning 100.
선행: 085(런타임 인터페이스)·089(conformance)·099(agent-flow 코드젠)·057(A2A 단일화)·042(a2a_client)·
064(net_guard). 검증: `tests/verify_100_broker.py`(53단언, 3런).

## 무엇을 했나

능력(에이전트·MCP·RAG·memory)을 컨텍스트에 **preload**하지 않고 **discovery**로 오케스트레이션하는
브로커 시임을 도입했다 — `discover(query)→기술→invoke` 3박자 하나. Phase 1은 kind=`agent`(A2A provider)만.

- **계약**(`packages/agent/runtime.py`): `Capability`·`InvokeResult` dataclass + `CapabilityBroker`
  `@runtime_checkable` Protocol. `AgentBuildContext.broker` 필드로 주입(에이전트는 이 핸들만 봄 — 정책·DB
  미접촉, 085 주입 단일 출처).
- **구현·정책**(`packages/api/broker.py`): `PolicyScopedBroker` — 생성 시 `(에이전트 allowlist) ∩
  (유저 RBAC)`로 미리 스코프. `_permitted` 단일 헬퍼(drift 0), deny-by-default, discover는 allowlist를
  SELECT WHERE에 밀어 거부행을 로드조차 안 함, invoke는 호출 경계 재검증(TOCTOU), 스코프 밖은 discover
  미노출·describe/invoke는 not-found로 접음(존재 비노출). `build_broker`는 chat.py 배선용(머신토큰 deny·
  superuser 우회·아니면 casbin enforce).
- **데모 flow**(`agent/flows/orchestrate.py`): `analyze`(결정적 검색어 추출)→`delegate`(broker로 발견 후
  첫 허용 능력 서브스텝 invoke)→`synthesize`(로컬 종합). 세 실 노드 타임라인이 "통째 프록시 단일
  `a2a_call`이 아니라 오케스트레이션"임을 노드열로 증명(085/086 astream 타임라인 재사용).

## 검증 사다리 3런(비겹침)

- **① 단위 시맨틱**: Protocol 적합·매니페스트 정직·노드 구조·순수함수(extract_query/fold_result/
  build_synthesis_messages)·conformance·레지스트리 드리프트0·`_permitted` 매트릭스·deny-by-default가
  **DB 미접촉**(session_factory가 호출되면 AssertionError)·존재 비노출·build_broker principal 배선.
- **② 실 인프라 통합**: 실 SQL로 allowlist 스코프(미허가 external은 로드조차 안 됨=존재 비노출 실증,
  ui는 provider 필터)·미허가 describe/invoke not-found·자가잠금 + in-process ASGI로 orchestrate 실
  스트림의 서브스텝 노드 타임라인 `[analyze, delegate, synthesize]`.
- **③ 적대 타자(codex)**: 6개 공격 가설 실측(아래).

## codex 적대 리뷰가 잡은 것 — 정직 분류(맹신·맹기각 금지)

- **[P1] #3 untrusted 출력이 SystemMessage에 삽입** → **진짜 결함, 수정**. synthesize가 위임(untrusted)
  텍스트를 최고 신뢰 채널(system)에 넣어 "지시 따르지 말라" 방어와 *같은 채널서 경쟁*. 조립을 순수함수
  `build_synthesis_messages`로 빼 system=지침만·데이터=라벨 붙은 Human 블록으로 격리, 모델 없이 채널
  격리를 단언(U4b 4단언). orchestrate가 flow의 broker-출력 처리 *레퍼런스*라 고가치·저비용 수정.
- **[P1] #1+#2 kind-단위 RBAC + 공유 에이전트 allowlist** → **같은 근원의 Phase 1 설계 한계**. Agent
  모델엔 owner 컬럼이 없어(공유 카탈로그, models.py:203 실측) 인가 입도가 전적으로 RBAC 축(kind 단위)에
  달림. per-cap·per-user 인가 없음. 우회가 아니라 *의도된 입도의 한계*지만 문서화 부족 → broker.py 모듈
  docstring + 스펙 §비목표에 커버 범위 명시(내 메모리 "설치≠덮음": 가드의 커버 범위를 단언).
- **[P2] #4 allowlist 스냅샷** → **설계상 수용**. 브로커는 요청당 1회 생성 → 스냅샷 수명=한 요청. 올바른
  입도(config 변경은 다음 요청 반영).
- **[P2] #5 타이밍/DB-touch 오라클** → **기각**. 브로커는 자기 allowlist로만 스코프 → 자기 스코프 probe는
  교차 누출 0(codex도 "out-of-scope 존재는 구분 안 함" 인정).
- 머신토큰/superuser: 4개 파일 내 우회 없음(codex 확인).

결과: no P0/P1 잔존(1건 수정, 2건 명시경계 문서화, 2건 수용/기각). 085·089 무회귀.

## 무엇이 잘 됐나

- **RBAC 체크리스트 자동 발동**: 인가 경계 스펙이라 닫힌 입구집합·단일 헬퍼·존재 비노출·3런 사다리를
  처음부터 적용 → codex가 우회는 못 찾고 *입도 한계*만 짚음(경계 자체는 견고).
- **순수함수 규약(099)**이 또 벌었다: 분기·조립 로직을 노드 클로저 밖 모듈 함수로 빼둔 덕에 codex #3
  수정을 모델 없이 단위로 못박음. 클로저에 묻었으면 채널 격리를 실LLM 통합으로만 볼 뻔.
- 기존 시임 재사용으로 신규 표면 최소화: A2A 전송(042/064)·타임라인(085/086)·conformance(089)를 그대로
  얹어 브로커는 "정책+시임"만 새로.

## 아팠던 것 / 다음에

- `_FakeAgent`에 `token` 속성 누락으로 P4 첫 실행 죽음 — broker가 `a.token`을 A2A 호출에 넘김. 페이크는
  실제 참조되는 *모든* 필드를 채워야(모델 스키마 아닌 사용처 기준).
- codex 리뷰 범위: 미커밋+신규(untracked) 파일이라 diff가 안 잡혀 파일 직독 지시로 전환. 신규 파일 리뷰는
  `git diff` 말고 파일 경로를 직접 주는 게 확실.
- 다음(백로그): admin UI impl/capabilities 편집(085 H5), 능력 브로커 Phase 2(kind 확장 + 인가 입도).
