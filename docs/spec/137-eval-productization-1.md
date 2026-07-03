# 137 — 평가 하네스 제품화 1탄: 데이터셋 DB + 실행 API + 어드민 UI

## 배경 / 왜
사용자: 평가 하네스(119)를 화면에서 — 문제집 CRUD·시험 실행·성적표. **문제별 필수/금지 도구
(mcp/rag/memory) 사용 채점 필수 포함.** 후속 "RAG 컬렉션 자체 평가"가 같은 골격을 재사용하도록 설계.
수치 검증→자율 반복(Ralph) 로드맵의 전제.

## 조사 확정 사실 (deep-reasoner, 파일:라인 근거)
- **오염 제로 실행**: `chat()` 재사용은 불가 — persistHistory=False여도 세션 lazy-create+turns 갱신+
  자동 memory.add는 못 끔. 정답=`stream_local_reply`(A2A 서빙용 순수 컴퓨트) 골격 + `event_stream`의
  **관측 수집부**(observed/calls_sink/broker invocations) 이식 + **build_broker 주입**(stream_local_reply엔
  broker가 없어 조율형 위임이 안 돎 — 주입해야 broker_invoke:* 채점 가능).
- **도구 채점의 함정**: 조율형 위임=그래프 노드(broker_invoke:*), 직접형 MCP/RAG=calls_sink(트레이스
  mcp), 메모리 회상=used_memory 플래그 — 형태가 셋. **obs를 canonical 토큰 union으로 정규화**
  (그래프 노드 + `mcp:{server}/{tool}`·`rag:...` + `memory:used`) 안 하면 직접형 도구 사용을 놓쳐
  조용한 초록(회고 100 대죄) 재발.
- 선례 재사용: BatchRun(상태머신 running|ok|error+summary)·batch_routes(백그라운드 잡+폴링+
  authz.require)·PagedListShell(목록)·SessionsView(목록→Drawer 성적표)·models 컨벤션(_pk/owner_id).

## 설계
### 스키마 (4테이블, models 컨벤션)
- `eval_datasets`: id·name(unique)·description·**kind('agent'|'rag' — RAG 평가 확장축)**·owner_id·시각.
- `eval_cases`: id·dataset_id(FK CASCADE)·name·input(질문)·asserts(JSONB 선언 목록)·order_idx·시각.
  asserts 예: `[{"type":"trace_has","arg":"rag:"},{"type":"output_contains","arg":"문해력"}]`.
- `eval_runs`: id·dataset_id·agent_pk·status(running|ok|error)·score·passed·total·summary·error·
  owner_id(실행자)·started/finished.
- `eval_case_results`: id·run_id(FK CASCADE)·case_name·passed·details(assert별 [이름,bool])·obs(캡).

### 하네스 승격
`tests/eval_harness.py` → `packages/api/src/api/eval_harness.py`(코어 단일 출처). tests는 import 경로
갱신(move-breaks-references — verify_119 수정). 선언 JSON→scorer 매핑: type∈{trace_has,trace_lacks,
no_error,output_nonempty,output_contains} (닫힌 집합 — 미지 type은 검증 오류로 거부, eval fail-closed).

### 러너 (오염 제로)
`eval_run_agent(agent, case_input) -> obs`: _load_context→tools/broker 구성(build_broker 주입 —
조율형 지원)→graph.astream(messages+updates)→obs 조립. **_persist·memory.add 호출 없음**,
checkpointer=None(HIL cap은 fail-closed 실패로 관측 — 평가 중 승인 대기 없음). obs.trace_nodes =
union 정규화(그래프 노드 ∪ mcp:{server}/{tool} ∪ rag 토큰 ∪ memory:used).

### 실행/API (admin 전용 — batch 미러, 1탄 안전 기본값)
`authz.require("eval",...)`. 데이터셋/케이스 CRUD + `POST /eval/datasets/{id}/runs`(EvalRun(running)
즉시 반환, asyncio.create_task로 **케이스 순차** 실행 — 실모델 rate-limit·격리) + `GET /eval/runs`·
`/eval/runs/{id}`(폴링·성적표).

### UI — 새 메뉴 "평가"
AdminShell 4곳 추가. 데이터셋 목록(PagedListShell 아님 — 소수라 DataTable로 시작 가능, 증가 시 셸) →
상세(케이스 목록+**assert 편집기**: 유형 Select+인자 입력 반복 행) → "시험 실행" 버튼 → 런 목록(폴링)
→ 성적표 Drawer(케이스별 pass/fail Tag + assert별 상세 + obs 요약).

## 단계 (커밋 분할)
① 스키마+하네스 승격+CRUD API, ② 러너+run API(+검증), ③ UI(+브라우저 검증). 회고는 ③ 후 일괄.

## 검증
- verify_137: ①CRUD 왕복+선언 asserts 검증(미지 type 거부) ②러너 오염 제로(**실행 전후 세션 수·
  mem0 행 수 불변 측정**)+직접형/조율형 union 채점(둘 다 rag: 토큰 잡힘)+HIL cap fail-closed
  ③run 상태머신(running→ok, 오류 시 error). 브라우저: 데이터셋 생성→케이스 2개(필수 rag 채점 포함)→
  실행→성적표. codex 적대(러너 오염·RBAC·선언 매핑 인젝션).

## 비목표 (OUT)
- 실행 이력 비교/추이(2탄), LLM-judge(3탄), RAG 컬렉션 평가 러너(kind='rag' 축만 마련 — 후속),
  member 실행 개방(1탄 admin-only), 케이스 병렬 실행.
