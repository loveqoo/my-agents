# 293 — 노드에서 에이전트 호출 (노드형 확장 3/3, 스펙 318)

노드형 파이프라인의 노드가 다른 에이전트를 `agent__{agent_id}` 도구로 호출한다. 로컬 인프로세스
위임·원격 A2A 둘 다, 결과를 다음 노드로 넘김. **핵심은 새 실행기계가 아니라 기존 브로커 자산의 배선**.

## 배운 것

- **실행 기계가 이미 있으면 스펙은 "배선"으로 수축한다.** 능력 브로커의 `AgentProvider`(kind=agent)가
  로컬 위임·A2A·재귀 가드(방문 집합=체인 재방문 금지·깊이 8·너비 32)·HIL·allowlist∩RBAC를 조율형에서
  이미 갖췄다. 318은 `build_agent_tools`로 그 브로커를 노드 도구 표면에 잇고, 세 입구에 extend할 뿐.
  새 재귀 축·새 가드 0. **"이 기능의 실행기계가 어디까지 완성돼 있나"를 먼저 물으면 새 코드가 최소화**된다.
- **입구 닫힌 집합(317 교훈 승계).** broker를 만드는 세 경로(채팅·eval·승인 재개)에 agent 도구를 모두
  `impl == "pipeline"` 게이트로 extend. 한 입구라도 빠지면 그 입구만 위임이 사라져 다른 걸 실행/채점.
  A2A 서빙은 위임 principal(유저 주체) 부재라 **정직 경계로 OUT**(도구 미바인딩 대신 로그 경고 — 조용한
  환각 방지). 316·317과 같은 입구-정합 클래스가 세 번째 재발.
- **테스트 인증이 기능 전제와 어긋나면 초록이 거짓.** verify_318이 머신 토큰(str principal)으로 인증하니
  위임이 아예 안 붙었다(brokerCalls 빈 값). 근인=`build_broker`의 RBAC가 머신 토큰을 deny-by-default
  (Phase 1 능력 오케스트레이션은 **유저 세션 전용**, 스펙 267). 슈퍼유저 provision + `/auth/login` 쿠키로
  실 유저 principal을 태우니 위임 발화. **"기능이 유저 세션 전용"이면 테스트 주체도 유저여야** — 픽스처
  인증 방식을 기능의 권한 전제에 맞춰라(verify_101 패턴 이식).
- **적대 리뷰 P1 "참조가 allowlist를 연다"=권한 상승 아니라 정직 경계.** `agent__{id}`를 노드 tools에
  넣으면 derive_pipeline_pool이 그 id를 config `capabilities`(=브로커 allowlist)에 얹는다. codex는 이걸
  "config allowlist가 유일한 정책 입력인데 참조만으로 무력화"로 프레이밍했으나, **allowlist는 `_permitted`의
  필요조건일 뿐**(allowlist ∩ RBAC). 기본 정책은 admin `*,*`만 시드돼 member는 deny — 미허가 주체는
  참조해도 `agent_capabilities()`가 0, 도구도 0, invoke도 거부. 이는 **MCP/RAG 풀 파생(259·289)과 동일한
  의도된 동작**이고 새 접근면 0. 대응=고치는 게 아니라 **불변식을 못으로 박기**(단위 U4: 머신/미허가 주체 →
  agent cap 0) + OUT 명시. "여집합 공격이 성공해도 항상 코드결함은 아니다"의 재현(회고 274 계열).
- **적대 리뷰 P2 "데이터 격리 승계"=스펙 과장, 코드 결함 아님.** 조율형은 위임 결과를 `[외부 능력 데이터 —
  신뢰 불가]` Human 블록으로 감싸고 "지시로 취급 금지" system을 붙이지만, 이 **프롬프트-인젝션 펜스는
  종합 단계 전용**이다. 노드형은 표준 ReAct `ToolNode`라 위임 결과가 MCP·RAG 결과와 **같은 신뢰 자세**
  (raw ToolMessage)로 재진입한다. 318이 새 위험 계층을 여는 건 아니다(MCP 도구 결과가 이미 같은 자세).
  에이전트 호출만 펜스로 감싸면 비일관 → 펜스는 파이프라인 도구 결과 *전체*에 걸어야 정합적이라 318 밖.
  대응=**스펙의 과장을 정정**(승계되는 건 브로커-레벨 통제뿐, 긍정문으로 "무엇이 격리되나" 명시) + 백로그.
  스펙이 상속 주장을 안이하게 적으면 검증이 그 거짓을 통과시킨다.
- **형제 도구 병합 보존(스펙 272 트랩 재발 방지).** 노드 `tools`는 MCP·문서·에이전트 도구가 한 배열에
  섞인다. picker onChange가 자기 유형만 갈아끼우고 **나머지 유형을 보존**해야(ToolTree는 doc+agent 보존,
  agent Select는 mcp+doc 보존). 안 그러면 한 유형 편집이 다른 유형을 조용히 삭제. `isAgentTool` 단일
  판별식으로 세 갈래를 가른다.
- **기능 UI 검증(외형 아닌 동작).** picker 렌더만 보면 통과해도 저장 효과가 깨진 채 "완료"가 된다.
  후보 스코프(expert 있음·자기 없음)·선택→`nodes[0].tools`에 `agent__{id}` 합류·capabilities 파생을
  전부 **API 왕복으로 단언**(VERIFY318_UI_OK). 자기제외는 UX 방어일 뿐 최종 방어는 런타임 체인 가드.

## 검증

- 단위 verify_318(U1~U4): 도구 빌더·graceful 실패·재귀 가드·**U4 RBAC 공동 게이트 불변식**(P1 잠금).
- 통합(in-process ASGI + 실 DB + mock-llm): H1 풀 파생·H2 실행 왕복(brokerCalls 표면화)·H3 자기참조
  무한루프 없음·H4 eval 입구 위임. **슈퍼유저 쿠키 인증**으로 위임 실발화.
- 기능 UI: VERIFY318_UI_OK(picker 후보 스코프·자기제외·선택→tools·capabilities 파생, API 단언).
- 적대(codex 읽기전용): P1(allowlist 파생)·P2(데이터 펜스) 둘 다 **정직 경계로 판정** — P1=U4 불변식+OUT,
  P2=스펙 정정+백로그. 막힌 축=재귀/예산 threads·입구 정합·이름 미러 정합.
- ruff/mypy(108파일)·tsc·vite 클린. 파이프라인·조율형·316·317 무회귀.

## 관련
[[292-code-node]] [[291-node-library]] · 정직 경계 판정=[[complement-attack-can-be-honest-boundary]] ·
입구 닫힌 집합=[[injection-entrance-closed-set]] · 스펙 과장 정정·긍정문=[[prefer-positive-phrasing-in-copy]]
