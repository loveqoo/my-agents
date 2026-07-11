# Backlog — 작업 후보 보드 (AI 영역)

> Scaffolding의 **진입 재료**. "다음 뭐 하지?"에서 이 파일을 먼저 읽어 후보/완료/보류를 한눈에 본다
> (대화 재유도 대신 스캔). 굵은 단위(후보 작업)만 — 서브태스크는 안 쪼갠다(파편화 방지). learning/
> retrospect/spec의 `INDEX.md`가 회고 상기를 싸게 만들듯, 이 파일은 *백로그 상기*를 싸게 만든다.
> 규칙이 아니라 종이 한 장 — 새 작업 정해지면 여기서 옮기고, 끝나면 완료로 내린다.

## 후보
- [ ] OTEL 계측(회사 이식 다리 — 관측 백엔드 교체 가능하게 Langfuse 직결을 한 겹 추상화, Prometheus/Grafana는 회사에 준비됨)
- [ ] 오버라이드 서랍 2단계 모바일 실기기 확인(스펙 249 잔여 — 사용자 "다음에") — 사용자 실사용 후보 10건 (2026-07-03 접수, 원문 보존·성격별 묶음)

### A. 버그/즉시 (실사용 차단)
- ✅**#1 기본 모델 설정=스펙 150 완료**(2026-07-03, 회고 128) — 원래 항목: **#1 기본 모델 설정(버그)**: provider에서 기본 chat/embedding 모델 변경이 안 됨(삭제 후 재등록만 가능).
  메모리 유사도 검색이 mock embedding에 묶여 있는데, mock 모델이 컬렉션에 참조 중이라 제거도 불가.
  → 기본 모델 전환 API+UI(삭제 없이 is_default 이양). 컬렉션 바인딩(차원 고정)은 유지한 채 *기본*만 전환.
- ✅**#2 MCP 상세 정보=스펙 151 완료**(2026-07-04, 회고 129) — 원래 항목: **#2 MCP 상세 정보(버그/공백)**: 등록 화면에 하위 툴의 메타정보(이름·설명·파라미터)가 노출되지 않고,
  MCP 기능을 들여다보는 화면 자체가 없음. → discover가 파라미터 스키마까지 수집·저장, 상세 드로어 신설.

### B. A2A/MCP 공개 체계 시리즈 (3~8 — 한 묶음, 스펙 시리즈로)
- ✅**#5 재공개 금지=스펙 152 완료**(2026-07-04) — MCP 3입구 봉인+source 불변+배선 fail-closed(에이전트는 083 기봉인).
- ✅**#6 organization 설정=스펙 153 완료**(2026-07-04, 회고 131) — app_settings 저장소 신설(범용 기반, #7·#9 재사용).
- ✅**#3 커스텀 에이전트 A2A 공개=스펙 154 완료**(2026-07-04, 회고 132) — 승격/강등 신설(백로그 ③ 흡수)+code 1홉 중계.
- ✅**#8 플레이그라운드 A2A 루프백 테스트=스펙 155 완료**(2026-07-03, 회고 133) — 직접/A2A 경유 토글+클라 stream 파서+154 후속 배지 게이트 정직화. A2A=단발·비영속 인라인 배너로 정직화.
- ✅**#4 내부 MCP 외부 공개 + 커스텀 MCP=스펙 156 완료**(2026-07-03, 회고 134) — to_fastmcp+FastMCP를 /_served/mcp/{name}에 서빙(외부가 붙음), source=custom 신설·공개 가드·무인증 서빙 안전 불변식. codex High1(유래 시스템전용)/Med1(멱등 reconcile)/Low1(도구 allowlist).
- ✅**#7 A2A skills 확장=스펙 157 완료**(2026-07-03, 회고 135) — 카드가 실제 능력(MCP·delegate·rag) 광고+플그 칩. codex High1(누출+거짓위임 봉인)/Med2/Low1. **B 시리즈(#3·#4·#5·#6·#7·#8) 전부 완료.**

### C. 플랫폼 방향 (대형)
- **#9 buddy agent(메뉴별 도우미)**: 143(평가 도우미)의 확장 — 기본 chat/embedding이 실모델일 때
  각 메뉴 기능을 가이드·대행. #1(기본 모델 설정)이 사실상 선행 조건.
- **#10 피드백→평가 데이터 수확(롱텀 하네스)**: 유저 응답/랜덤 피드백을 평가 케이스·선호 데이터(DPO류)로
  축적해 응답 고도화. 평가 백로그의 "세션→케이스 수확"·"인간 리뷰 층" 씨앗과 합류.

## 후보 (다음에 할 만한 것) — 새 방향 4개(사용자 "모두 차례대로", 순서대로)

- ✅ **방향 1 — A2A 협업 실증 + 위임 승인 게이트**(스펙 117) 완료 → 아래 완료.
- ✅ **방향 2 — 관측·측정 계층(Langfuse)**(스펙 118) 완료 → 아래 완료.
- ✅ **방향 3 — 에이전트 평가 하네스(수치)**(스펙 119) 완료 → 아래 완료.
- ✅ **방향 4 — 저마찰 생성(복제)**(스펙 120) 완료 → 아래 완료. **4개 방향 전부 소진.**

### 후속 씨앗 (급하지 않음)
- **런타임 도구명(_safe_name) 전역 유일성 검증**(codex 289 #5) — MCP 서버명+도구명·컬렉션 문서
  도구명이 60자 절단·문자 치환으로 충돌하면 by_name이 마지막 것을 조용히 선택. 생성/수정 입구에서
  런타임명 충돌 검증(스펙 148 네이밍 계열). 289 파생은 모호 민이름만 fail-closed로 부분 방어.
- ✅**노드형 풀 서버측 파생 → 스펙 289 P2로 완료**(2026-07-11) — 원 항목: (스펙 288 실측 #2 후속) — API로 직접 만든 노드형은 vectorTables/memories
  풀이 비어 노드 도구가 조용히 미바인딩(폼 derivePipelinePool만이 파생 책임). 서버가 저장/실행 시
  노드 합집합에서 풀을 스스로 파생하면 폼 밖 입구(API·A2A 등록)도 안전 — learning 151(조용한 미바인딩)
  의 구조적 봉합 후보.
- **조합 스위트 artifact(HIL 폼) 시나리오**(스펙 288 P2 OUT) — artifact_form 픽스처+폼 왕복 관측 표면
  실측 후 시나리오 2개 추가. 스위트는 `tests/suite/run.py`(실모델 게이트), 새 기능 추가 시 scenarios.py
  한 줄 추가까지가 한 단위(회고 263).
- ✅**노드형 오버라이드 세부에 Temperature 재검토 → 복귀 완료**(2026-07-10 사용자 결정, 같은 날 등재분) —
  실측(pipeline.py:79)상 에이전트 temperature가 모든 노드에 우선 적용되므로 오버라이드 세부에 복귀.
  적용 범위 문구("모든 노드의 모델에 적용") 동봉, 직접형과 공용 TemperatureField로 통합. verify-287에
  존재+페이로드 동봉 단언.
- **RAG 컬렉션 평가 도구**(사용자 제안 2026-07-03, 평가 하네스 1탄 후속) — 에이전트 평가와 비슷하게,
  수집된 RAG 자체를 평가: 질문→기대 구절/문서 데이터셋으로 검색 품질(히트 여부·유사도·순위) 수치화.
  임베딩 모델 교체·청킹 정책 변경의 회귀 검증용. 1탄(에이전트 평가 제품화)의 데이터셋·실행·성적표
  골격을 재사용할 수 있게 1탄 설계 시 염두.
- **템플릿/프리셋 생성**(방향 4 OUT) — 미리 만든 시작점(조율형 봇·RAG 봇·빈 에이전트). 복제로 부분 충족.
- ✅**평가 하네스 제품화 1탄=스펙 137 완료**(2026-07-03) — 문제집 DB·오염제로 러너·평가 메뉴. ✅2탄(추이+비교)=스펙 138 완료(2026-07-03). ✅3탄(LLM-judge)=스펙 139 완료(2026-07-03). ✅4탄(RAG 컬렉션 러너)=스펙 140 완료(2026-07-03) — **평가 시리즈(137~140) 전체 마감**. 남은 씨앗: 심판 모델 선택 UI·다중 심판 합의·다중 컬렉션 동시 평가·인제스트 품질 진단·장기 추이.
- ✅**모델별 비교+격자=스펙 141 완료**(2026-07-03, 조사 learning 141 기반). ✅골든셋 자동 생성=스펙 142 완료(2026-07-03). 이후 씨앗: 프롬프트 축 격자·judge 신뢰성(심판 벤치마크)·expected 1급 필드·RAG 표준 메트릭(faithfulness류)·인간 리뷰 층·세션→케이스 수확.
- **메뉴별 도우미 에이전트(플랫폼 방향, 사용자 제안 2026-07-03)**: 기본 chat+embedding이 실모델(mock 아님)이면 전용 도우미 에이전트를 가동해 어떤 메뉴·기능이든 돕는 구조. ✅**1탄=평가 도우미(AI 출제)=스펙 143 완료**(2026-07-03).
- **다음 루프 대기열(2026-07-03 갱신2)**: ✅①스펙 148 네이밍 규칙 완료(회고 126, 데이터 초기화 포함) ✅②엔티티 RAG=스펙 149 완료(회고 127 — JSONL 계약+JSON Schema 검증+meta 동반 검색; v2 씨앗: DB 직결/메타 필터 검색/upsert/엔티티용 평가 assert(rag_meta_contains류)/meta 구조 분리) ✅③private→public 승격=스펙 154에 흡수 완료 ④148 잔여 씨앗: rename 시 참조 자동 갱신·casbin per-cap 동반 갱신·페르소나/권한/MCP 폼 e2e
- **현재 모드(2026-07-03~): 사용자 실사용 테스트·보완 단계** — 평가 v1(137~143) 완비, "모두 맘에 드는 건 아님" → 실사용 피드백으로 기능 보완. 새 대형 스펙보다 사용자 보고 기반 교정 우선. 보고 오면: 재현(브라우저/DB 직접) → 진단 → 스펙化 여부 판단. 이후 후보: 컬렉션 도우미(인제스트 진단), 에이전트 빌더 도우미(페르소나 초안), 세션 도우미(요약·분류).
- ✅**회상 진단 위장 버그=스펙 158 완료**(2026-07-04, 회고 136, 실사용 버그 "기억 있는데 유사도 검색 안 됨") — 근인=mem0 숨은 기본 threshold=0.1 상속→저유사도 전부 컷·"정상·0건" 위장(+M1 예외삼킴 부차). 수정=recall_diag threshold=0으로 top-k 표시(낮은점수까지→자가진단)+저장건수 진단+파사드 3분기(챗[]/브로커error/진단표면화)+로그 비밀 마스킹. codex High1/Med1. **후속 씨앗(OUT)**: arctic query-prefix 임베더 주입·재인덱싱 도구·챗 회상 threshold 튜닝(제품 결정).
- ✅**임베더 차원 강제 버그=스펙 159 완료**(2026-07-04, 회고 137, 158 진단이 표면화한 진짜 원인) — 근인=MEM0_EMBED_DIMS가 컬럼차원+임베더요청차원 겹쳐 써 dimensions=1024 강제→snowflake(256만 허용) 400. 수정=네이티브 차원 probe(RAG 방식)해 네이티브==컬럼 미전송·≠면 컬럼길이 전송(정적기본값은 한쪽 깸). 비파괴(11건 보존). codex 2R(정적미전송 회귀→probe, 캐시키·타임아웃·env검증). **사용자 배포본에서 회상 복구 확인 완료**(다른 디바이스 정상). **후속 씨앗(OUT)**: 컬럼 마이그레이션 도구·모델별 컬럼차원 저장·broker 810/931 to_thread.
- ✅**임베딩 query/passage 접두어=스펙 160 완료**(2026-07-04, 회고 138, 158·159 OUT 후속) — 비대칭 모델(e5·arctic) 접두어를 mem0가 무시→action별 주입(설정형 env, 기본 no-op). **측정 우선**: 로컬 e5 접두어 효과 미미 실측→하드코딩 대신 설정형, arctic만 켜게. arctic=query만·비파괴(기존 저장 무변경). codex 결함0. **후속 씨앗(OUT)**: passage 접두어용 재인덱싱 도구·모델별 접두어 UI. **배포본에서 arctic 접두어 켜고 회상 품질 실측 대기**.
- **Langfuse 수동 span/score**(방향 2 OUT) — 자동 계측 위에 커스텀 점수(평가 하네스 연동).

### 후속 씨앗 (급하지 않음)
- **다단 승인 큐**(스펙 116·117 OUT) — 다중 gated/A2A cap 순차 위임 시 두 번째 이후 interrupt를 chat.py
  resume 경로가 새 Approval row로 승격(현재는 고아, 안전은 fail-closed 유지). 101/102 다중 interrupt 완전성 갭.
- **A2A 승인 payload args 스냅샷 바인딩**(스펙 117 OUT) — "승인==전송"을 임의 브로커 호출자까지 일반보장
  (재개 간 args 비결정 대비). 기본 orchestrate 경로는 이미 안전.
- **a2a.delegate self-approve 시드**(스펙 117 OUT) — 현재 admin만 승인(fail-closed). 소유자 self-승인(105 선례).

- ✅**비영속 도구 경계=스펙 237 완료**(2026-07-08, 회고 215 — DB 쓰기 능력(memwrite/memedit)만 금지·MCP/RAG 허용, 235 'interrupt 구조적 불가' 가정 실측 반증·승인 경로 계약위반 봉합)

## AgentOps 루프 로드맵 (2026-07-08 채택 — 사용자+외부 에이전트 논의안 검토 후 확정)
> 방향: 피드백→수확→평가→버전 비교→개선의 운영 루프. 제안의 절반은 기존 자산(209 수확·137~143 평가·
> 138 회귀 비교·205 실측)이 이미 커버 — 진짜 갭 4개를 순서대로. Snapshot은 "완전 재현" 대신
> **EvalRun 경량 환경 기록**(진단 단서)으로 경량화(과설계 회피, 필요 실증 시 확장).
- ✅**A. 평가의 버전 귀속=스펙 240 완료**(2026-07-08, 회고 218) — EvalRun.agent_version+env(마스킹·조인), UI 버전 칩·환경 접이식. 다음=B
- ✅**B. 활성화 시 자동 회귀=스펙 241 완료**(2026-07-08, 회고 219 — may_manage 필터·버전 dedupe·자동 회귀 태그)
- ✅**버전 지정 실행(사용자 방향 삽입)=스펙 242 완료**(2026-07-08, 회고 220 — 내부 버전별 서빙(config 소스 전환)·초안 평가=배포 전 게이트·may_manage 403). ✅**243 플그 버전 선택=완료**(2026-07-08 — 헤더 버전 Select·미리보기 배지·인스펙터 버전). **다음=D 운영 화면**
- ✅**D. 버전 운영 화면=스펙 244 완료**(2026-07-08, 회고 221 — /ops 집계+버전 행 칩, codex 4건 수정). **AgentOps 로드맵 A~D 전부 마감**(240~244). 남은 항목=C(수확 맥락 풍부화)·루프 자동화(cron)는 후속 후보
- **C. 수확 케이스 맥락 풍부화** — 수확 시 trace(도구·RAG 흔적) 연결 (후순위 잔여)
- (이후) 루프 자동화: cron 수확+자동 평가. 주의: 자동 회귀는 실모델 전제, 피드백 표본은 👎 편향이라 회귀 비교용.

- **승인 화면 개편(복잡도 진단 1위 — 스펙 245 P2 발견)**: 117블록·컨트롤 233·세로 22화면 분량 — 승인 행 전부를 카드로 렌더+페이지네이션 없음(데이터 비례 성장). 처방 후보: 서버 페이지네이션(PagedListShell 재사용, 스펙 128)+상태 필터(대기 우선)+처리된 행 접기. UX 개편 다음 1순위
- ✅**code/external 상세 페이지 승격+죽은 코드 정리=스펙 246 후속4 완료**(2026-07-08, 사용자 지적 — DetailPageShell 공용화·AgentDetail.tsx 삭제)

## 진행 중

- (없음)

## 보류 / 후속 후보

- **antd 전환 보류 5건**(스펙 204, 사용자 결정 "교체 18건만 먼저") — ①TrendChart 생 SVG(antd 코어
  무차트—@ant-design/plots 도입은 별 스펙) ②MessageContent/JsonTree(대응물 없음) ③DataTable 모바일
  카드 분기(→List 후보) ④InlineFormPanel·트레이스 카드 겉면(→Card/Form 표준화) ⑤components/Chat.tsx
  죽은 코드 삭제. 재론 시 docs/spec/204 참조.
- **커스텀 impl이 무시하는 설정을 폼이 경고 없이 수용하는 함정** (스펙 201 후속2에서 실사용 확인) —
  plan_execute(도구 미사용 플로우)에도 편집 폼이 mcps 피커를 노출해 사용자가 연결→조용히 무시→"발동
  안 됨" 혼란. 처방 후보: CustomAgent 매니페스트(describe)에 "소비하는 설정 표면" 선언→폼이 미소비
  표면을 숨기거나 경고. 스펙 108(kind-aware 폼)의 커스텀 impl 일반화.

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

- **인스펙터 정직성 3건(스펙 205, 2026-07-07)** — 전송 프롬프트 콜백 실측·토큰 usage 실측·턴=질문
  순번. 실모델 7/7.

- **도구 다수 시 디스커버 전환(스펙 203, 2026-07-07)** — 임계 10 초과 시 메타 도구(search_tools/
  call_tool)로 컨텍스트 보호, 브로커 미경유(권한 보존), live 전 체인 검증. 후속 씨앗: 벡터 검색(카탈로그
  확대 시)·승인게이트 도구 HIL·오버라이드 드로어 문구.

- **'능력 부여' UI 개편(스펙 199 진단→200 구현, 2026-07-07)** — 카탈로그 Select(판정 키=value)·문장화·역할/유저 분리·도입 문장·종류 6종 완성. e2e 18/18.

- **드로어 모바일 최적화 → Escape 닫기 통일**(스펙 135, 점검 5탄) — 6개 드로어 점검(가로 넘침 0),
  갭=닫기 수단 불일치 → 커스텀 Drawer·인스펙터에 Escape 추가. E1~E5 2회 PASS. 완료(2026-07-03). 미푸시.

- **턴 트레이스 오버라이드 기록**(스펙 134, 점검 4탄) — "오버라이드한 세션 재진입" 질문 진단(오버라이드=
  UI 적용 상태, 세션 무관) → 턴별 trace.overrides+인스펙터 섹션+과거 세션 토스트. codex 2건(적용 가드
  미러·토스트 타이밍) 수정. 완료(2026-07-03, 회고 114). 미푸시.

- **전 메뉴 모바일 점검 스윕**(스펙 133, 점검 3탄) — 11메뉴 390px 순회: 정상 11·수정 2(승인 세로 압착
  버그·블록 탭 잘림). 교훈=정량 지표는 flex 내부 압착을 못 잡음(육안 페어 필수). 완료(2026-07-03). 미푸시.
  후속이던 'Drawer Escape 닫기'는 스펙 135로 완료(마스크 탭 불가는 구조상 수용).

- **플레이그라운드 모바일 헤더 v2**(스펙 132, 점검 2탄) — v1(아이콘만)을 실기기 피드백이 뒤집어
  세로 스택 3줄+온전 텍스트(fullWidth)로. 검증 8/8×2. 완료(2026-07-03, 회고 113+v2 추기). 미푸시.
  **점검 남은 항목**: 인스펙터/오버라이드 드로어·채팅 영역 모바일 최적화.

- **인스펙터 상세화**(스펙 131) — 전송 프롬프트 전문(sentMessages: 캡+개수상한+마스킹)·브로커/RAG 결과
  본문(resultPreview)·노드 값(query/route/delegated 실값). 가림 계보(086/087) 추적해 관문대로 개방.
  codex 4건(무마스킹×2·무상한·부분표면화) 수정. 새로고침 영속 복원까지 e2e. 완료(2026-07-03, 회고
  112·learning 131). 미푸시. 플레이그라운드 점검(사용자 제기)의 1탄 — 후속 점검 항목은 논의로.

- **조율형 RAG 검색 표면화**(스펙 130) — "RAG 검색 안 함" 신고를 진단으로 반증(검색은 동작·표시가 구멍),
  hits/topScore 구조화→trace.brokerCalls(3경로 전수)→인스펙터 "검색 N건·최고 유사도"+관련도낮음 태그+
  메시지 칩 rag 카운트. codex 3건(경로 누락 P2×2·오표시 P3) 수정. 완료(2026-07-03, 회고 111·learning
  130). 미푸시. **후속 씨앗**: 플레이그라운드 UI 개선·기능 점검(사용자 제기 — Scaffolding서 논의).

- **세션 종료 버튼 배선**(스펙 129) — 목업 버튼에 endSession+Popconfirm+드로어 완료 전환+목록 재조회.
  검증이 "백엔드 완성" 전제를 반증 — 첫 실호출 500(commit 후 onupdate 컬럼 만료→MissingGreenlet,
  커밋 성공+응답 실패=거짓 실패 UX)→refresh 1줄 수정. fast-worker 10/10 PASS·DB completed 확인.
  완료(2026-07-03, 회고 110·learning 129). 미푸시.

- **PagedListShell 일반화**(스펙 128) — 127 엔진을 공용 셸로 추출, 세션(프론트 이관+토스트→지속오류)·
  컬렉션 문서(백엔드 페이지 API 신설)·메모리(소비자 재작성) 3면 공유. 컬렉션 목록은 소수라 OUT.
  codex 2건(과도기 요청·토스트 중복)+사용자 신고(드로어 absolute 스크롤 깨짐→fixed) 수정. 완료
  (2026-07-03, 회고 109·learning 128). **후속 씨앗**: keyset(대규모 시). 세션 end 배선은 스펙 129로 완료.

- **메모리 서버 페이지네이션 + 일치/유사도 통합**(스펙 127) — 증가 데이터 대응: list_page 추상 계약+mem0
  raw SQL(20건 캡 버그도 수정)+PagedMemoryList(Segmented 일치|유사도, SessionsView 패턴). 첫 오케스트레이션
  실전(deep-reasoner 조사·fast-worker 브라우저·codex 적대). 완료(2026-07-02, 회고 108·learning 127). 미푸시.
  후속 씨앗이던 '세션/컬렉션 일반화'는 스펙 128로 완료. keyset은 계속 보류.

- **메모리 조회를 드로어→상세 페이지 인라인**(스펙 126) — "넓게 활용". 검색시험 셸이 컬렉션과 공유라
  본문을 RetrievalTestPanel로 추출·드로어는 얇은 래퍼(컬렉션 무변경)·메모리는 상단 Card 전체폭+목록 아래
  (위아래 스택, 사용자 선택). RecallPanel 신설·RecallDrawer 삭제. codex NO ISSUES. 완료(2026-07-02,
  회고 107·learning 126). **미푸시**.
- **메모리 검색 "왜 0건인지" 관측성**(스펙 125) — 다른 노트북 배포서 유사도검색 안 됨+이유 불명. 근인=
  `recall_probe`가 미가용 3사유를 None 하나로 뭉갬+검색예외 500→사라지는 토스트. `recall_diag`(예외 삼켜
  4모드 구조화)+`diag` 필드+프론트 지속 진단패널(백엔드상태·임베딩모델·스코프·오류). 재현불가 환경을
  관측성으로 옮김(고치는 대신 화면에 "왜"). 비밀=실제 api_key 정확치환. codex 2건(마스킹 gaps·실패≠0건)
  수정. 완료(2026-07-02, 회고 106·learning 125). **미푸시**.
- **조율형이 도구/문서/기억 못 씀**(스펙 124) — broker.discover의 어휘 하드필터(`쿼리⊆능력`)가 자연어
  쿼리서 허가된 능력을 전부 떨궈, 조율형이 discover로 아무 능력도 못 찾던 버그. 필터→랭킹 전환(토큰 겹침
  순, 하드 드롭 안 함). allowlist∩RBAC 게이트 불변. verify_124 7/7+브로커 verify 무회귀+codex 없음.
  버그 필터에 의존하던 GREEN 테스트(101 H2·100 P2)는 진짜 불변식으로 교정. 완료(2026-07-02, 회고
  105·learning 124).
- **오버라이드 그룹 헤더 오토글**(스펙 123) — 플레이그라운드 오버라이드에서 그룹 헤더(기억) 클릭이 다른
  그룹(도구) 첫 체크박스를 토글하던 버그. 근인=`Field`가 `<label>`로 PickerGroups(다중 컨트롤)를 감싸
  label 클릭이 첫 하위 컨트롤로 전달. `Field.group`(div role=group)로 수정+Temperature 방어. 회귀
  브라우저 검증(헤더 불변·실제 토글 정상·Temperature 불변)+122 무회귀. codex 여집합. 완료(2026-07-02,
  회고 104·learning 123).
- **사용자 버그 2건**(스펙 121·122) — (1) RAG/MCP 삭제 가드가 **과거 버전** 참조에도 막히던 과엄격을
  **활성 config만**으로 완화(093 전-버전 스캔 완화, usedBy 배지와 재정렬). 부수로 verify_093이 112
  게이트 추가로 조용히 red였음 발견·복구. (2) 조율형 플레이그라운드 오버라이드에서 **설정한 MCP 누락**
  (108 편집폼만 kind로 가르고 109 오버라이드 누락) → OverridePanel kind-aware+chat.py 허용목록+
  isOrchestratorImpl 단일소스. 각 codex clean, 버그2는 브라우저 검증. 완료(2026-07-02, 회고 102·103,
  learning 121·122).
- **에이전트 복제**(스펙 120, 방향 4) — 저마찰 재사용(POST /agents/{id}/clone + 상세 드로어 복제 버튼).
  복제=읽기+새생성→원본 관리권한 불요(가시하면 복제, 사용≠관리)·복제자 소유(069)·행위설정만 복사
  (card 제거). 버튼은 can_manage 밖에 ui/code/external 3 드로어 모두. verify_120 13/13 + 브라우저
  shot-clone-120. 방향 4(마지막) 완료(2026-07-02, 회고 101·learning 120). **4개 방향 전부 소진.**

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

## 실사용 피드백 (C 시리즈 보류 중 처리)
- ✅**페르소나 수정 반영=스펙 161 완료**(2026-07-04, 회고 139) — 페르소나 편집이 에이전트에 반영 안 되던 것(스냅샷 복사). 라이브참조 기각(사용자: 복사=영향도격리 좋음)→템플릿→인스턴스 동기화(오래됨 배지+명시 반영, can_manage 게이트). codex High(usage 가시성 누출) 수정. **후속 씨앗(OUT)**: 페르소나 버전/롤백·저장 후 드로어 유지 즉시 stale·apply 원자 최신본문.
- **C 시리즈(#9 메뉴별 도우미·#10 피드백→평가 수확)는 보류**(2026-07-04, 사용자 "둘 다 백로그로") — 실사용 피드백 우선 처리 모드.
- ✅**mem0 테이블 미생성 목록 502=스펙 162 완료**(2026-07-04, 회고 140, 실사용 버그 초기화 직후 `relation "mem0_memories" does not exist`) — mem0 lazy 생성 테이블을 list_page 직접 SQL이 우회→UndefinedTable→502. 수정=UndefinedTable만 빈 상태로("실패≠0건" 158의 대칭 함정). codex 결함0/Low경계1(문서명시). **후속 씨앗(OUT)**: 리셋 시 mem0 선생성·리셋 UX(기억 0건 안내)·42P01 미초기화vs drop 구분.
- ✅**RAG 컬렉션 사용 공개=스펙 163 완료**(2026-07-04, 회고 141, 실사용 "공개 설정 없어 공유 못 함") — 컬렉션 published 플래그+publish 토글(MCP 미러), "사용만 공개"(수정·삭제는 소유자). codex High(직접 search가 게이트없이 청크 유출)→may_use_collection로 search+documents 봉인. **후속 씨앗(OUT)**: 공개 컬렉션 필터·PII 경고·평가 러너 사용게이트.
- ✅**프로바이더 테스트 "모델 미발견"=스펙 164 완료**(2026-07-04, 회고 142, 실사용 버그) — 프로바이더 레벨 테스트가 빈 model_id로 _probe 호출→무조건 "미발견". 수정=빈 model_id면 목록 개수로 판정("모델 N개 발견"). 프론트 무변경. **후속 씨앗(OUT)**: 발견 모델 목록 응답 포함·embedding 프로바이더 테스트.
- ✅**도구 무발동 진단성=스펙 236 완료**(2026-07-08, 회고 214 — toolDiag 인스펙터 표면화+폼 mock경고+mock 이름언급 일반트리거로 wiki 실발동) — 원래 항목: **도구 무발동 진단성 + mock 모델 한계 (실사용 2026-07-07, 다른 기기서 web-fetch 트리거 안 됨)** — 사용자가 공개·허용호스트·배선을 다 맞췄는데도 web-fetch(위키) 트리거 안 됨. 근인 **모델 층**(폼·배선 아님, 앞선 진단이 다 헛다리): (1) **mock-llm은 tool_call을 `delete_record`·`search_documents` 두 도구·키워드에만** 냄(mock_remote.py `_TOOL_TRIGGERS`) → wiki_search/wiki_page 등 **임의 도구는 mock서 영영 무발동**; (2) 유일 실 도구모델 qwen3.6-35b는 **로컬 MLX(`localhost:8045`)=이 Mac 한정** → 별도 배포엔 실모델 부재 → mock 강제 → 무발동. **진단성 갭이 핵심**: 세 게이트(공개·허용호스트·배선) 다 통과해도 **조용히** 무발동, "왜"를 표면화하는 신호 0 → 사용자가 한 세션 내내 엉뚱한 층 추적. 처방 후보: (a) 에이전트 모델이 mock일 때 폼/플그에 "이 모델은 도구를 호출 못 함(실모델 필요)" 표면화; (b) 도구 바인딩됐는데 모델이 tool_call 무발화 시 인스펙터/트레이스에 "모델이 도구를 호출하지 않음" 진단(회상 진단 158·검색 진단 125의 결); (c) mock 트리거를 등록 도구 일반으로 확장(실습성) 또는 최소 web-fetch 키워드 추가. **관련**: 71–74줄 "폼이 무시 설정 수용"(스펙 201 후속2, 다른 층=폼 게이트)은 스펙 202/206서 일부 해소.

## 지속 검증 체계 (사용자 제기 2026-07-04 — 자가검증이 관대함)
- ✅**축2 다디바이스 UI 오버플로 감사=스펙 165 완료**(회고 143) — `tests/browser/ui-audit.mjs` 하네스(전수 순회+수치판정+스크린샷). 원리=도구가 좁히고 육안이 확정. 파일럿으로 batch 버튼잘림 1건 발견·수정. ✅축1(사용 시나리오 감사)=스펙 166 완료(회고 144, J1·J2 7단계 ok·막힘0, 핵심경로 건전·초안 대화 잘 처리). ✅축3(문구·평이함 감사)=스펙 167 완료(회고 145, 내부 산출물 누출 12건 수정). **3축 파일럿 완료.** ✅드로어/모달 오버플로=스펙168·✅감사 커맨드화+스킬=스펙169(`/ui-audit`·audit-all.mjs, 회고147) 완료. **검증 아크(165~169) 마감.** **다음 후보**: 자율 감사 cron 실제 등록, 카피 축 기계화(LLM judge), 감사 커버리지 확장(세로잘림·중첩드로어), 또는 새 기능 방향(C시리즈 buddy agent·피드백 수확). ✅**RAG 공개/비공개 제거=스펙 172 완료**(회고 150·163 되돌림): 사용자 교정—public/private·공개/비공개 개념 RAG서 전면 제거, 사용=전부 공용(익명 401)·관리 소유자만. 별명 편집(실제 의도)=스펙 173 완료(회고 151, 편집 드로어 노출). ✅**메뉴 감사=스펙 174 완료**(회고 152): 관리자 그룹 5개 서버 강제 확인·프로바이더·모델(상단이나 변이 관리전용)을 관리자 그룹으로 이동. RAG 임베딩 UX=스펙 175 완료(회고 153). RAG 별명 편집 발견성=스펙 176 완료(회고 154, 행 편집 연필 버튼+전용 모달, 문서 드로어 설정패널 제거). ✅**승인 재개 impl-drift 가드=스펙 171 완료**(회고 149): deep-reasoner 적대 검토로 승인 로직 점검→유일 Low(stale 주석·impl 교체 재개)를 명시 가드로 닫음. 잔여(pre-migration pending 행·완전 런타임키 스냅샷)는 문서화. ✅**평가 도구 정직성=스펙 170 완료**(회고 148): 평가 통과≠도구 호출을 성적표 배지+출제 안내로 표면화. 후속: 메모리 vs 히스토리 의문①=**조사 완료**(learning 143)—mock이 추출 무너뜨려 안 보임(실 모델서 demo-mem-vs-history.mjs로 크로스세션 1 mem 실증 가능)·info-circle 아이콘 잔존 버그(AgentsView:1950, 맵키 info). ✅**드로어·모달 오버플로 감사=스펙 168 완료**(회고 146, 14/14·FAIL0 오버레이 반응형 건전, learning142 부산물). 후속 씨앗: 모바일서 현재 메뉴 재탭 시 사이더 백드롭 안 닫힘(controlled Menu onSelect 같은key 재발화 안 함, 실동작 경계). **축3 후속(백로그)**: mem0 라이브러리명 노출(백엔드 시드 memory type 이름)·`차원` 글로스·배치/프로바이더 admin jargon(SQL LIKE·grant·keep-list)·영어 enum 태그(kind·transport)·용어 사전 상시화.

## 구조 리뷰 후보 (스펙 182/183 발견, 2026-07-05 — deep-reasoner 2병렬 OCP/HoC 점검)
> 사용자 신념("당장 구현보다 구조") 점검. 백엔드 OCP·프론트 HoC. 결론: 소스 대체로 건강(메모리 백엔드·에이전트 런타임·서빙 MCP·remote축=진짜 레지스트리 OCP, DIP/LSP 준수). 정리감은 아래.
- ✅**source 제1자/제3자 축 술어=스펙 183 완료**(회고 164) — is_remote_source 자매 축 미적용 봉합(리터럴 7곳→술어).
- **브로커 kind 파싱 부분 OCP**: provider 라우팅은 레지스트리(`_by_kind`)인데 `_kind_of`(broker.py:57)·`_cap_resource`(broker.py:101)가 하드코딩 if-체인. 새 kind 시 함께 수정—`_cap_resource` 누락하면 per-cap RBAC 리소스 추출 오동작(인가 게이트 조용한 오류, 스펙 112 경계). → provider 계약에 흡수(`matches(cap_id)`/`resource_of`)해 순회 파생. **중간 우선**.
- **broker.py 1180줄 단일 모듈** → provider들을 `broker/` 패키지로 분할(응집도 높으나 파일 격리 개선). 낮음.
- ✅**프론트 useAsyncData/runWithToast 훅=스펙 184 완료**(회고 165) — `admin/src/hooks.ts`. 소비자 3곳 변환(AllowedHosts·Memory 2탭). **남은 것**: 나머지 ~11개 뷰 점진 이관(기계적, fast-worker 위임 후보). 폼시드 패턴(SettingsView류)은 훅 부적합—제외.
- ✅**AgentsView.tsx 분해=스펙 185 완료**(회고 166·167): **Phase A**(서브컴포넌트 8개 파일분리, 2128→747줄)+**Phase B**(useAgents 훅으로 데이터 오케스트레이션 격리, 747→684줄). tsc0·브라우저 회귀 2종 ALL PASS(파일분리 3드로어/폼/모달 + 뮤테이션 왕복 커스텀토스트 보존)·스샷. runWithToast 미채택(커스텀 플로팅토스트 보존). **남은 것(저위험 점진, 선택)**: 나머지 ~11개 뷰 useAsyncData 이관(fast-worker 위임 후보).
- **HoC는 불필요**(리뷰 결론): AuthGate(render-prop)·PagedListShell(제네릭)이 HoC 니치 이미 덮음. 권한 게이트는 표현 분기(인라인/조각). 넣으면 과설계=신념 배신.
- **테스트 부채(183서 발견)**: verify_152 V4 "code→400" stale(154가 code 노출 허용, 단언 갱신 필요)·verify_083 노출게이트 5건 404(라이브 인프라/시드 의존).

## antd v6 deprecation 전면 마이그레이션 (스펙 207서 관측 → ✅스펙 208 완료, 2026-07-07)
- ✅**스펙 208 완료**(회고 196): 관측 3종 전수 처리(Alert message→title 30·Drawer width→size 13·List→Flex 4), 완료기준=콘솔 deprecation 경고 0건 달성. 공용 래퍼 Drawer는 내부 1곳만 고쳐 소비자 무변경 커버. **후속 씨앗(OUT)**: 다른 v6 deprecation(bodyStyle·destroyOnClose·Card bordered 등)이 감사에 새로 뜨면 그때 처리.

- [ ] 노드형 인스펙터 노드 행 정보 확충(추후, 스펙 262 후속) — 노드별 모델·출력형식(JSON) 배지·carry/clean 표식 등. 지금은 실행 흐름에 이름·시간·요약·격리 노트까지.

- [ ] 노드형 "마지막 노드만 응답으로" 옵션(스펙 264 관찰) — 중간 노드 출력(계획 등)이 최종 답 앞에 스트림돼 섞임(원 plan_execute는 plan 무토큰). 중간 노드는 인스펙터만·최종 노드만 사용자 응답으로 하는 노드/에이전트 옵션 검토.
- [ ] 노드형 기억: 장기 미선택(단기만) 노드의 "조용한 회상 없음" 안내(스펙 268 주의 — memory_enabled는 장기 블록만). UI 힌트 or 게이트 표시 검토.
- [후보] 기본 public + 생성자 축 분리(번호 미정 — 285는 resync가 사용) — 284에서 분리(2026-07-10): 현 모델 공개=owner_id 소멸이라 "기본 public+내 것 tint" 양립 불가. created_by 신설(마이그레이션)+147 가시성 게이트(404-fold·복제·A2A·메모리) 재설계. RBAC 체크리스트+codex 적대 필수.
- 네비 메뉴명 "메모리" vs 화면 어휘 "기억" 통일 검토(회고 261 — 286서 상세만 통일, 반쪽 상태)
- shot-agent-policy-147·shot-naming-148 e2e — 284(소유 태그·필터 소멸)로 대상 표면 소멸, 수리 또는 폐기 판단 필요(286서 발견)
- antd v6 deprecation 신규 관측: Descriptions labelStyle→styles.label (154 콘솔, 208 규칙에 따라 후속)
- [후보] 낡은 verify 스크립트 2건 수리: verify_036_rag_ingest(KeyError 'id')·verify_056_session_cleanup_counter(3건 FAIL) — 291 이전 커밋 worktree 차등으로 기존 부채 확정(2026-07-11 재검증). ~~verify_038~~은 기존 부채가 아니라 **Phase 2 회귀**(keyword-only run_id 개명)였고 mypy 도입(Phase 4)이 적발·수리, ALL PASS 복귀. 교훈: stash 차등은 미커밋만 걷어냄 — 기준점은 스펙 시작 전 커밋 worktree로.
- [후보] verify_100_broker.py P1 사전 실패: _FakeAgent에 active_version 속성 없음 — 스펙 256 위임 게이트(active_version 검사) 이후 픽스처 미갱신. 원본/분할판 동일 실패(2026-07-11 Phase 3b-2서 차등 확정). 낡은 verify 3건(036·038·056)과 같은 부류.
- [후보] verify_103_broker_rag.py(coroutine StopIteration)·verify_130/131(invocations[0] IndexError) P1 사전 실패: 스펙 294서 pristine HEAD 동일 실패로 차등 확정(내 변경 무관, 낡은 mock/픽스처). verify_100과 같은 stale verify 부류 — 일괄 갱신 대상.
- [후보] verify_190_nocode_artifact.py P1 사전 실패: langgraph produce_node()에 config 인자 누락(버전 시그니처 드리프트). 스펙 295서 pristine HEAD 동일 실패로 차등 확정(무관). stale verify 부류.
- [후보] 스펙 296 = 남은 공통화 B: api A2A 프레이밍 3중(mock_remote↔a2a_server)·get-or-404 인라인 36곳→db.get_or_404·_card_streaming·_assert_valid_name→naming·_non_blank. authz _own_scope/_is_admin은 저자 의도(라우터 독립)라 설계판단+적대검증 별도. eval_* 계열 중복은 미전수(추가 조사).
- ✅**스펙 297 = get-or-404 정본화 완료**(2026-07-11, 회고 272). session.get+404 관용구→`db.get_or_404[T]`(PEP695). 전수=**37곳**(예상 36 아님): 1차 분류 33 + 견고 스캐너가 잡은 멀티라인·꼬리주석 near-miss 4(eval_cases2·eval_authoring2)—"정규식 놓침을 무해로 방치"가 census-lens 재발이라 전량 편입. 순수 PK-get만·결합게이트 제외·존재-404→assert_may_manage 순서보존. verify_112/147/148/104+스위트 51/51·codex 여집합 결함0. **에이전트 dedup 4연작(294~297) 마감.**
  - [잔여 백로그] authz `_own_scope`/`_is_admin` dedup(라우터 독립성 설계판단+적대 필요)·eval_* 내부 중복(미전수)·stale verifier 일괄 갱신(100/103/130/131/190/084).
- [후보] verify_084_memory_search.py P1 사전 실패: fake `A` 객체 .source 누락(스펙 183 이후 픽스처 미갱신). pristine HEAD 동일 실패 확정(무관). stale verify 부류(100·103·130·131·190과 함께).
- [후보] verify_061_a2a_exposure 사전 실패: chat.stream_local_reply monkeypatch 실효 안 함(원본에서도 동일 실패 — 3b-1 차등 확정). 관련: chat 분할 후 파사드 재할당은 분할 모듈에 늦은 바인딩 안 됨(codex 3b-1 Low — 미문서 경계로 기록, 실사용 테스트 0. monkeypatch 필요 시 각 모듈 심볼을 직접 패치).
