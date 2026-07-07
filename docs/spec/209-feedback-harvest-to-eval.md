# 209 — 응답 피드백(👍/👎) 수집 → 평가 케이스 수확 (에이전트 변경 회귀 지표)

## 배경 (사용자: "좋아요/싫어요로 개선, DPO 같은 것" → 논의 → "평가로 수확·좋아요도·실제 세션까지")
채팅 응답에 👍/👎를 받아 개선한다. **DPO 정정**: 우리는 모델을 학습하지 않고 등록 모델을 base_url로
쓴다 → "학습"은 밖. 대신 피드백을 **평가 케이스로 수확**해 우리 강점(수치 검증)에 얹는다. 핵심 가치:
**피드백 = 에이전트 변경 안전망**. 👍=유지돼야 할 좋은 답(positive), 👎=다시 안 나와야 할 나쁜 답
(negative). 에이전트(페르소나·모델·도구) 변경 후 수확 문제집 재실행 → 점수로 "좋은 건 지키고 나쁜 건
고쳤나" 측정([[numeric-verification-unlocks-autonomy]]).

## 결정된 스코프 (사용자)
- 👍·👎 **둘 다** 수확(👍=회귀 유지 지표 — 사용자 명시).
- 수집: 플레이그라운드 **+ 실제 채팅 세션**.
- 수확: **초안 케이스 + 관리자 검토** 후 편입(자동 편입 OUT — LLM assert 오류가 평가 오염).

## 설계

### A. 피드백 수집 (백엔드)
- 새 모델 `MessageFeedback`: `id·message_pk(FK assistant Message)·session_pk·rating('up'|'down')·
  reason(Text, 선택)·created_by(auth User UUID str)·created_at·harvested_case_id(nullable, 수확 후 링크)`.
  message당 (created_by) 1건(재클릭=토글/수정, upsert). assistant 메시지에만.
- 엔드포인트: `POST /sessions/{sid}/messages/{mid}/feedback {rating, reason?}` (upsert)·`DELETE`(취소).
  응답 메시지 목록에 내 피드백 포함(GET 세션/턴에 feedback 필드).

### B. 소유권 경계 (docs/spec/CLAUDE.md 체크리스트 — 세션/사용자 데이터)
1. **입구 열거(닫힌 집합)**: feedback set(POST)·unset(DELETE)·read(세션/메시지 GET에 포함)·
   harvest(👍/👎→케이스, 별도)·수확 케이스 read/편입. A2A 단발(세션 없음)=입구 아님(피드백 대상 없음).
2. **입구별 소유권**:
   - set/unset: **세션 소유자만** 자기 세션 메시지에 피드백. 남의 세션 메시지=404(존재 비노출).
     SELECT WHERE session.user==principal로 거부행 미로드(fetch-then-check 금지).
   - read: 피드백은 세션 소유자·에이전트 소유자·admin이 봄(세션 스코프 상속).
   - harvest: **에이전트 소유자/admin만**(수확=평가 자산 생성, 관리 행위). 케이스 스탬프 owner=수확자.
   - 익명/미인증 세션(embed·A2A): created_by None → 피드백 불가(MVP, 인증 principal만). 정직 경계.
3. **단일 헬퍼**: 세션 소유 판정은 기존 `_own_scope`/세션 소유 헬퍼 재사용(드리프트 0).
4. **존재 비노출**: 볼 수 없는 세션/메시지는 404(403 아님).
5. **검증 사다리 3런**: 단위(피드백 upsert/토글)·통합(seed+restart, 소유자만 set·타인 404)·적대(codex:
   타인 세션 메시지에 피드백 주입·수확 권한 우회·익명 세션 피드백).
6. **자가-잠금 핀**: 정당한 소유자가 자기 세션에 피드백 가능(조임이 본인 차단 안 함).

### C. 수확 → 평가 케이스 (eval_suggest 패턴 재사용)
- 트리거: 에이전트 상세/평가에서 "피드백 수확" — 그 에이전트 세션들의 피드백을 모아 **초안 케이스** 생성.
- 케이스 생성: (질문=피드백 메시지 직전 user 메시지, 답=assistant content, rating, reason)을 LLM에 주어
  **assert 초안** 합성(eval_suggest.suggest_agent_cases 로직 확장):
  - 👍 → positive: "답이 [좋았던 답의 요지]를 담는가"(judge criterion) 또는 핵심구 contains.
  - 👎 → negative: "답이 [사용자 지적 문제]를 피하는가"(judge) 또는 must-not 조건.
- 편입: 에이전트별 **"피드백 수확" 문제집**(dataset)에 draft로 → 관리자가 EvalView에서 검토·수정·활성화
  (기존 draft 케이스 검토 UI 재사용, 스펙 193). label에 `feedback:up|down` 태그.
- harvested_case_id로 피드백↔케이스 링크(같은 피드백 재수확 방지).

### D. 지표 사용 (에이전트 변경 안전망)
- 수확 문제집은 기존 평가 러너로 재실행 → 점수. 에이전트 변경(페르소나·모델·도구·버전) 후 재실행해
  positive 유지·negative 개선을 수치로 확인. (별도 자동 트리거는 OUT — 수동 재실행 MVP.)
- **실행 대상 고정(2026-07-07, 사용자 지적 보완)**: 수확 문제집은 `source_agent_pk`(출처 에이전트)를 실행
  **대상으로 고정** — RAG가 `collection_id`로 컬렉션을 고정하는 것과 동형(스펙 193). 목적이 "이 에이전트
  바꾼 뒤 회귀 확인"이라 매번 고를 필요 없음. `DatasetOut`에 source_agent_pk 노출·EvalView가 "대상
  에이전트" 칩으로 고정(드롭다운 제거)·실행/AI출제 모두 이 에이전트 사용. (초기 Phase 2는 source_agent_pk를
  idempotent 재사용·읽기 게이트에만 쓰고 실행 대상 배선을 빠뜨린 빈틈 — 저장한 링크를 그 목적까지 잇지
  못함. 사용자가 잡음. 검증: 브라우저 e2e — 칩 고정·드롭다운 0·시험 실행 시작.)

## 실행 (단계)
- **Phase 1 — 수집**: MessageFeedback 모델+마이그레이션(f209a1b2c3d4)·엔드포인트(PUT upsert/DELETE)·
  세션 GET messages에 id+feedback·소유권 게이트. UI: **세션 뷰(SessionsView) 응답에 👍/👎+이유**
  (재사용 FeedbackButtons). **완료(2026-07-07)**.
- **Phase 1.5 — 플레이그라운드 피드백**: 플레이그라운드 응답 버블에도 👍/👎. `_persist`가 assistant
  Message.id를 반환하게 하고 스트림에 message_id 프레임 방출 → ChatMsg.id로 부착. **완료(2026-07-07)**.

## 검증 결과 (Phase 1.5, 2026-07-07)
- **백엔드**: `_persist`가 flush 후 assistant Message.id(str) 반환. `_mid_frame` 헬퍼로 `event: message_id`
  프레임 방출 — SSE 스트림 4곳(A2A remote·ask·form·direct main). 5번째(resume_approval)는 비제너레이터
  (-> None)라 스트림 없음 → 재개 턴 피드백은 **세션 리로드**(GET /messages, Phase 1의 id+feedback 재사용).
- **프론트**: ChatMsg += id/feedback. streamChat `onMessageId` 콜백·handleFrame이 message_id 이벤트 파싱.
  Playground `onMessageId`→appendToLastAi(id 부착)·loadSession 매핑에 id+feedback(과거 세션 복원 시 피드백
  표면). DebugChat이 id 있는 완료 응답에 재사용 FeedbackButtons 렌더(currentSessionId 사용).
- **육안 e2e(브라우저)**: 플레이그라운드 응답에 👍/👎 렌더 → 클릭 → "이유" 버튼(평점 설정) → **DB 영속**
  실측(`up` · '[mock-llm] "플그 피드백 영속 테스트"'). 이 플그 피드백도 Phase 2 수확 대상이 됨.
- 회귀: 209 스위트 18/18·24/24·tsc0·ui-audit 42화면 FAIL0(플그 무오버플로). codex 생략(가산적·소유권
  경계는 Phase 1 codex 검증 재사용, 새 경계 없음). (verify_049는 무관한 스테일 테스트 — `_create_approval`
  시그니처 불일치, Phase 1.5와 무관.)
- **Phase 2 — 수확**: 수확 엔드포인트(피드백→초안 케이스, LLM assert)·"피드백 수확" 문제집·EvalView 검토
  편입·harvested 링크(models에 harvested_case_pk 추가). **완료(2026-07-07)**.

## 검증 결과 (Phase 2, 2026-07-07)
- **모델/마이그레이션(f210a1b2c3d4)**: `MessageFeedback.harvested_case_pk`(→eval_cases, 재수확 방지 링크)·
  `EvalDataset.source_agent_pk`(→agents, 에이전트당 수확 문제집 idempotent).
- **`eval_harvest.py`**: `gather_unharvested`(Session.agent_pk 조인=크로스에이전트 격리, 미수확만·직전 user
  질문)·`harvest_agent_feedback`(👍/👎→llm_judge 기준 LLM 합성, **llm_cfg=None이면 폴백 템플릿으로 우아하게
  저하** — 수확은 질문이 실제 사용자 메시지라 LLM 없이도 유효, suggest와 다름).
- **엔드포인트**: `GET /eval/harvest-count`(미수확 수+기존 문제집)·`POST /eval/datasets/harvest`(find-or-create
  by source_agent_pk·`_active_jobs` 락·`_member_job_guard`·배경 `_execute_harvest`가 케이스별 harvested_case_pk
  스탬프). 소유권=`assert_may_manage(agent)`(에이전트 소유자/admin, 비소유 404-fold).
- **통합 verify_209_harvest.py 18/18**: 소유자 202·비소유 404(count+harvest)+문제집 미생성·수확→2케이스
  (질문=직전 user·assert=llm_judge·name 평점)·**크로스에이전트 격리**(agent2 피드백 불수확)·harvested 스탬프
  2건·재수확 0중복+같은 문제집·admin 임의 count.
- **e2e(브라우저, 실데이터)**: Phase 1에서 👍 준 plan-execute-demo 세션 → AgentDetail "피드백 수확" 패널에
  배지 1 → 클릭 → draft "피드백 수확 · plan-execute-demo"(1케이스) → EvalView서 열람. 케이스 질문=실제 사용자
  질문("한글 한 줄 요약"), 기준=LLM 합성("세종대왕 창제·1446 반포·훈민정음 포함하고 한 줄로 간결한가").
- tsc0. ui-audit 오버레이 FAIL0(agent-detail 수확 패널 무회귀).
- **codex 적대 검증(수확 여집합)**: 핵심 보장 유지(게이트 선행·크로스에이전트 무유출·created_by 불변·부분
  커밋 없음). 통합이 못 본 5건 발견→수리: **F1(High)** 수확 문제집 케이스(입력=사용자 질문)가 eval 공개
  읽기로 전원 노출→`_gate_harvest_read`(source_agent_pk≠NULL은 소유자/admin만·목록서도 필터, 스펙 §B
  세션 스코프 상속). **F2(High)** 동시 첫-수확 경합→2문제집·이중수확→`pg_advisory_xact_lock('harvest:'+agent)`
  로 직렬화(마이그레이션 없이). **F3(Med)** 무제한 수확 배경비용→`_HARVEST_MAX=50` 상한+절단 로그. **F4(Med)**
  미존재 에이전트가 admin에 `assert_may_manage(None,super)` 통과→count 200/harvest 500→`agent is None` 선행
  404. **F5(Low/Med)** 수확 문제집 소유가 수확자→admin이 남의 에이전트 수확 시 에이전트 소유자가 관리 불가
  →`owner_id=agent.owner_id`. 통합 24/24 재통과(F1·F4 신규 6체크 포함).

## 검증 결과 (Phase 1, 2026-07-07)
- **통합(seed+restart, rung 2) verify_209_feedback.py 17/17**: 소유자 upsert/토글(1건 유지)·assistant-only
  404·부재 404·**타인 세션 404 은폐+주입 실패**·머신 403·admin created_by별 분리·DELETE 내 행만.
- **육안(브라우저)**: SessionsView 드로어에서 assistant 응답에만 👍/👎+이유, 클릭→영속→리로드 렌더
  (초록 필드 👍 확인). DB 실측 1행·GET feedback 반환 실측(쓰기·읽기 정상).
- tsc0.
- **codex 적대 검증(소유권 여집합)**: 핵심 보장 유지 확인(크로스오너 주입 차단·머신 403·created_by 서버
  스탬프·읽기 스코프·DELETE own-only). 통합이 못 본 4건 발견→수리 3: **F1(High, 설정의존)** `sessions:read`
  권한자가 `_own_scope`로 타인 세션 쓰기→`_own_scope_write`(진짜 superuser만 무스코프) 신설·PUT/DELETE
  적용(단위 검증). **F2(Med)** 동시 첫 PUT 경합→unique 위반 500→PG `on_conflict_do_update` 원자 upsert.
  **F3(Med/Low)** reason 무제한→`Field(max_length=2000)`(라이브 422). **F4(Low)** 잘못된 UUID→422=수용
  (형식검증, 존재/소유 오라클 아님 — 모든 malformed에 균일). 통합 18/18 재통과.

## 검증
1. 단위: 피드백 upsert/토글·소유권(SELECT-WHERE 거부행 미로드)·수확 케이스 assert 생성.
2. 통합(seed+restart): 소유자만 set·타인 세션 404·수확은 에이전트 소유자만·수확 문제집 재실행 점수.
3. **적대(codex)**: 여집합 — 타인 세션 메시지 피드백 주입·수확 권한 우회·익명 세션·harvested 재수확 중복·
   assert 오류가 평가 오염(초안 게이트가 막나).
4. e2e(브라우저): 플레이그라운드/세션서 👍/👎+이유·수확→draft 케이스→검토 편입·재실행 점수 표면.
5. tsc0·ui-audit.

## 경계
- 모델 학습(진짜 DPO/SFT)은 OUT — 데이터셋 export(길 B)는 후속. 여기선 평가 수확만.
- 자동 수확·자동 재실행 OUT(초안+수동, 오수확·오염 방지).
- 익명/A2A 세션 피드백 OUT(인증 principal만, MVP).
- 개선 제안·페르소나 자동수정(길 C) OUT(별건).
