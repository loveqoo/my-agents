# 049 — 세션 정리 정책 (#10): 0턴 미영속 + 턴 기준 배치 정리

마스터: `044`(2026-06-28 어드민 테스트 14건) 배치5 — **#10 세션 정리 정책**.
사용자 결정(2026-06-28, AskUserQuestion): **"생성 시점부터 미저장 + 배치 보조"**(옵션 3).
"5턴 미만 미저장"을 글자대로 — 소스에서 빈 세션을 아예 안 만들고, 배치가 저턴 이탈분을 정리.

## 문제 (#10, 그리고 #11 정크 세션의 뿌리)
현재 `chat.py:_load_context`는 새 세션을 **즉시 INSERT+commit**(chat.py:209-219)한 뒤
session_pk를 하류 `_persist`에 넘긴다. 결과: **플레이그라운드를 열고 한 마디도 안 해도
0턴 빈 세션 행이 남는다** → 어드민 세션 목록이 정크로 가득(#11의 생성원). 또 짧게 한두 턴
주고받다 이탈한 저가치 세션도 영구히 쌓인다.

## 결정 — 두 메커니즘
### 1. 소스 미영속(0턴 세션 차단) — 핵심
세션 행 생성을 **첫 실 턴까지 지연**한다. `session_id`는 클라이언트가 후속 요청에 참조하므로
`_load_context`에서 **생성은 하되 commit은 안 한다**(보류). 첫 `_persist`(실제 user+assistant
턴이 발생한 시점)에서 행을 lazy-create.
- `_load_context`: 새 세션이면 commit 대신 `ctx["session_pk"]=None` +
  `ctx["session_pending"]={session_id, agent_pk, agent_name, channel}`. 기존 세션
  (session_id 매칭)은 그대로 reuse(session_pk 채움).
- `_persist`: `session_pk`가 None이고 `session_pending`이 있으면 → session_id로 get-or-create
  (unique 제약 경합은 flush→IntegrityError→re-select 폴백). 그 후 메시지/turns/commit.
- 효과: **0턴 세션은 DB에 영영 안 생긴다.** 한 턴이라도 오가면 정상 영속.

### 2. 배치 보조(저턴 이탈분 정리)
`BatchConfig.min_session_turns`(Integer, nullable, 기본 NULL=비활성) 추가. `cleanup_sessions`가
나이 기준에 더해 **`turns < min_session_turns AND last_activity < now - IDLE_GUARD`**인 세션도
삭제한다.
- **활성 세션 보호(핵심)**: `IDLE_GUARD`(상수 1시간) — 최근 활동 세션은 절대 안 건드린다.
  사용자가 옵션1(별도 유휴창 *설정*)이 아니라 옵션3을 골랐으므로 어드민 노브는 늘리지 않고
  내부 안전 상수로 둔다. cron은 보통 일 단위라 "1시간 내 활동분 보호"면 진행 중 대화는 안전.
- ge=1 + NULL=비활성(learning 037 — 파괴적 노브 바닥). min_session_turns=0이면 모든 세션
  대상이 되는 footgun이라 API에서 ge=1, jobs에서도 `<1` 가드 한 겹 더.
- 나이 기준 절(기존 retention_days)과 **합집합**. 둘 중 하나만 설정돼도 그 절만 작동, 둘 다
  NULL이면 no-op(disabled). dry-run은 두 절의 would_delete를 합산·표기.

## 변경 파일
- **models.py** `BatchConfig`: `min_session_turns: Mapped[int|None]` 추가 + docstring.
- **alembic**: `batch_config.min_session_turns` 컬럼 add_column 마이그레이션(head에서 분기).
- **batch_routes.py**: `BatchConfigOut`/`BatchConfigIn`(ge=1)/`_config_out`/`update_config` 필드 루프에 추가.
- **batch/jobs.py** `cleanup_sessions`: 턴 절 + IDLE_GUARD 추가, 반환 dict에 턴 정리 결과 합산.
- **chat.py** `_load_context`(보류) + `_persist`(lazy-create, ctx 경유로 시그니처 조정).
- **admin/src/admin/views/BatchView.tsx**: `최소 턴 수` InputNumber + dirty/save/applyCfg.
- **admin/src/api.ts** `BatchConfig` 인터페이스에 `min_session_turns` 추가.

## 검증 (자가 + 타자)
1. **소스 미영속(통합, self-fixture)**: 자체 에이전트로 `_load_context` 호출 → sessions count
   불변(0턴 미영속). 이어 `_persist` 1회 → 정확히 1행, turns=1, session_id 일치. 재호출(같은
   session_id) → reuse(중복 생성 X).
2. **배치 턴 정리(통합)**: 자체 세션 3종 시드 — (a) turns=2 & last_activity 2h 전(이탈),
   (b) turns=2 & last_activity 5분 전(활성), (c) turns=5 & 오래됨. `min_session_turns=3` →
   dry-run would_delete가 (a)만; 실행 후 (a) 삭제·(b)(c) 보존. **활성 세션 보호 실증.**
3. **나이+턴 합집합**: retention_days + min_session_turns 동시 설정 시 두 절 합집합 삭제, 중복 없음.
4. **비활성/검증**: min_session_turns=NULL → 턴 정리 no-op. API ge=1(0 → 422). jobs `<1` 가드.
5. **멱등**: 재실행 deleted=0. 메시지 cascade 삭제 확인.
6. **038 회귀**: 기존 나이 기준 cleanup_sessions 불변(verify_038 ALL PASS).
7. **프론트**: `tsc --noEmit` 0. 브라우저(Playwright): BatchView에 `최소 턴 수` 필드 렌더·저장.
8. **타자(적대 서브에이전트)**: lazy-create 경합으로 세션 유실/중복? IDLE_GUARD가 활성 세션을
   놓치나(경계)? 0턴 미영속이 approval-resume/외부A2A 경로(session_pk 의존)를 깨나? 턴 절이
   나이 절과 충돌? min_session_turns 경계값(1)이 delete-all로 번지나?

## 검증 결과 (2026-06-28)
- **통합(자가, self-fixture)**: `tests/verify_049_session_retention_policy.py` — **50 checks ALL PASS**.
  외부 소스 에이전트(`agt_v049_*`) + `v049_` 세션 prefix로 격리, agent_pk 단위 자가정리.
  - A(소스 미영속): `_load_context`→행 0 / 첫 `_persist`→정확히 1행·turns=1·메시지 2 / 재호출→중복 0·turns=2 /
    `_create_approval`→행 보장·turns=0·Approval.session_id 일치·resume `_load_context` 원세션 재발견(연속성).
  - B(턴 정리): IDLE_GUARD가 활성(5분) 보호·turns≥3 보호·idle만 대상(스코프드 술어) / 나이∪턴 합집합 중복 없음 /
    나이 기준 실삭제+메시지 cascade+멱등 / 둘 다 NULL→disabled / **잡-레벨 days<1·min_turns<1 가드**.
  - **C(API)**: `BatchConfigIn(min_session_turns=0)`→ValidationError(ge=1), 1·None 허용.
- **파괴 안전(learning 037/034)**: 라이브 DB에 **턴 기준 매치 126/130건**(실제 #11 정크) 확인 →
  적응형 가드로 비-fixture 매치 시 실삭제 생략(dry-run+스코프드만), 나이 100d 경로만 실삭제(extra=0). 남의 데이터 0건 삭제.
- **프론트**: `tsc --noEmit` 0. 브라우저(Playwright+시스템 Chrome): BatchView에 `최소 턴 수`(addonAfter=턴, 비활성 placeholder)
  렌더 + 패널 설명에 IDLE_GUARD 보호 문구 노출(`/tmp/batch049-1-view.png`).
- **타자(적대 서브에이전트)**: A~E 5축 리뷰. session_pk None-deref·lazy-create 경합·cross-agent 누출·합집합·tz·turns NULL =
  모두 clean. **MEDIUM 결함 #1 발견·수정**(아래).

## §7 빚·한계
- **[적대리뷰 #1, 수정완료] 미해결 승인(HIL) 세션이 정리될 위험**: `_create_approval`이 turns=0으로 만든 세션은 턴 절(<N)에
  걸리고 승인 대기는 흔히 IDLE_GUARD(1h)를 넘긴다 → 그 사이 배치가 행을 지우면 resume가 새 id를 만들어 대화가 고아.
  `cleanup_sessions`에 **pending approval 세션 제외(`~exists` AND, 양 절 공통)** 추가로 차단. 회귀: verify_049 B6(대조군 포함).
  → **연속성 보장은 *생성→정리* 전 구간에 걸쳐야 한다**(생성 시점만 막으면 다른 서브시스템이 깬다). learning 참조.
- **[행동 변화, 합의된 트레이드오프] 오류 첫 턴**: remote/A2A/local 첫 턴이 errored면 `_persist` 생략 → 클라에 흘린
  session_id가 DB 행 없이 남고, 재시도 시 서버가 새 id 발급. #10 의도(성공 실 턴 전 미영속)대로이며 대화 맥락은
  클라가 매 턴 전체 히스토리를 보내므로 유실 없음.
- IDLE_GUARD는 어드민 노출 안 하는 1h 상수(옵션3 선택 반영). 더 긴 유휴창이 필요하면 후속에서 노브화.
- lazy-create는 session_id 단위 get-or-create라 동시 첫 턴 경합도 안전하나, 플레이그라운드는
  순차라 경합은 이론적. 폴백(IntegrityError→re-select)로 방어.
- 턴 정리는 `turns`(비정규화 카운터) 기준 — _persist가 항상 +1이라 신뢰. 메시지 미저장 모드
  (persist_history=False)에서도 turns는 증가하므로 "대화량" 척도로 일관.
