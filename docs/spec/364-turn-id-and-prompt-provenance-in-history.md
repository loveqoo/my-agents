# 364 — 대화 이력에 턴 id + 프롬프트(페르소나) 출처 기록 (턴 단위 분석 복원)

## 왜 (사용자 목적)

**턴(쓰레드) 단위로 분석**하려는데, 이력에서 턴을 못 가른다. 런타임엔 턴마다 고유 thread_id가
있지만(chat.py:455 — 체크포인터 중복 누적 방지 위해 매 턴 `token_hex(4)` 랜덤 생성), 그 id는 그 턴의
재개/일시정지에만 쓰이고 **메시지에 안 남긴 채 버려진다**. 저장되는 건 세션·역할·본문·트레이스뿐
(chat_persist.py:91)이라, 이력을 보면 어느 유저 메시지와 어느 답이 같은 턴인지 시간순 말고는 묶을
근거가 없다. 그래서 턴 단위 집계·분석이 불가능하다.

부가로, "이 턴에 **어떤 프롬프트(페르소나)**가 쓰였나"도 분석 축인데 안 남는다. 게다가 페르소나는
config에 **이름**으로만 참조돼(chat_context.py:250, 서빙 때 이름→body 해석) 나중에 원본을 고치면 과거
턴의 실제 내용을 못 되짚는다(agentVersion은 config 스냅샷이나 페르소나 body는 원본을 따라 변함).

## 설계

한 턴의 유저·어시스턴트 메시지가 `_persist` 한 지점에서 함께 저장되므로, 거기서 두 행에 같은 스탬프를
찍는다(자매 표면 동시 처리, [[context-control-propagates-to-affordances]]).

### P1 — 턴 id (항목 2)

- `Message.turn_id`(String, index) 추가 — 한 턴의 유저+어시스턴트 두 행에 **같은 값**.
- 값 = **런타임 thread_id 재사용**(이미 턴마다 고유). 덤: 체크포인터/재개 로그와 상관 가능.
  caller(chat.py·chat_stream.py·chat_approval.py)가 이미 thread_id를 쥐고 있으니 `_persist`에 인자로
  넘긴다. 산출물형 재개(pending_artifact)는 같은 thread_id를 이어받으므로(chat.py:445) HIL/폼 재개가
  **한 턴으로 묶인다**(원자적 턴 경계 — 도구 루프·승인 재개 포함 1턴 1 id).
- 이력이 turn_id로 묶여 턴 단위 집계가 가능해진다.

### P2 — 프롬프트 출처, 스냅샷 방식 (항목 3, 옵션 b)

분석·재현이 목적이라 id/이름만(옵션 a)으론 원본 편집 시 내용을 잃어 부족. 프롬프트 버전관리(옵션 c)는
별도 서브시스템이라 과투자 — **스냅샷(b)**: 그 턴에 실제로 쓰인 프롬프트를 박제한다.

- **분석 축(컬럼)**: `Message.prompt_id`(uuid|null)·`prompt_name`(String|null) — 그룹핑·집계용(“어느
  프롬프트가 좋은 답을 냈나”를 컬럼으로 질의). 어시스턴트 행에 스탬프(유저 행은 프롬프트 무관).
  - chat_context 해석이 지금 `prow.body`만 반환(id 탈락, :252) → **prow.id·name도 함께 보존**하도록
    ctx에 싣는다. 이름 매칭 실패(라이브러리에 없는 인라인 텍스트)면 id=null·name=cfg["persona"].
- **재현(스냅샷)**: 그 턴에 쓰인 페르소나 **body 스냅샷**을 어시스턴트 trace(JSONB, 이미 턴별)에 담는다
  (`trace.promptSnapshot = {id, name, body}`). 컬럼 중복 없이 재현 데이터는 trace에.
- 오버라이드(스펙 xxx)로 그 턴 페르소나가 바뀌었으면 **해석 후 최종값** 기준(실제 쓰인 것이 진실,
  [[gate-on-intent-value-not-mutable-baseline]]의 "실제 값이 진실" 결).

### 마이그레이션 (한 번에 완결)

- alembic 리비전 1개로 `messages.turn_id`·`prompt_id`·`prompt_name` 3컬럼 + turn_id 인덱스 추가.
- **손수 순번 리비전 id 금지**([[hand-authored-migration-ids-collide-silently]]) — `alembic revision`
  자동 생성. down_revision=현재 head 확인 후.
- **--reload 중 편집 금지**([[reload-reruns-migrations-mid-edit]]) — 모델+마이그레이션을 한 번에 완성한
  뒤 부팅. 적용 후 DB에 컬럼 3개 실재 측정(단일 head·컬럼 존재).
- 기존 행: turn_id·prompt_* 전부 nullable(과거 이력은 turn 미상 — 소급 안 함, 신규 턴부터 기록).

## 완료 조건 (수치)

- **C1** 새 턴 저장 후 그 유저·어시스턴트 두 Message의 `turn_id`가 **동일·비어있지 않음**, 서로 다른 턴은 **다름**.
- **C2** HIL/폼 재개가 얽힌 멀티스텝 턴도 **한 turn_id**(재개 전후 같은 값).
- **C3** 어시스턴트 Message의 `prompt_id`/`prompt_name`이 그 턴 실제 프롬프트와 일치(라이브러리 참조면 id 有,
  인라인이면 id=null·name=본문키). `trace.promptSnapshot.body`가 그 턴 해석 body와 일치.
- **C4** 오버라이드로 페르소나 바뀐 턴은 **바뀐 값**이 기록(기준값 아님).
- **C5** 마이그레이션 후 단일 head·컬럼 3개 실재(DB 측정). 기존 채팅·이력 무회귀(make test SUITE_OK + 실채팅).
- **C6** ephemeral·persistHistory=false 턴은 기존대로 메시지 미저장(무회귀 — 스탬프도 스킵).

## 결과 (2026-07-15)

- 착지: `Message.turn_id`·`prompt_id`·`prompt_name` 컬럼(+turn_id·prompt_id 인덱스), `_persist`가 두 행에
  turn_id 스탬프·assistant에 prompt_id/name + `trace.promptSnapshot={id,name,body}`. caller 5곳
  (chat `_final_frames`·`_ask_frames`·`_form_frames`·chat_approval 재개·chat_stream A2A)이 turn_id 전달
  (로컬=런타임 thread_id, 원격 A2A=생성). chat_context가 프롬프트 id/name을 ctx에 해석(원격·오버라이드는 null).
- **prompt_id는 String(80)로 확정**(스펙 초안의 uuid에서 변경) — provenance는 프롬프트 삭제 후에도
  살아남아야 해 **FK 아님**, uuid 캐스팅도 불필요. 그룹핑/조인은 문자열로 충분.
- **마이그레이션은 프로그램적 생성/적용**: CLI `alembic`이 버전 파일의 `from api.models import ...`
  재-임포트로 **순환 임포트**(fastapi_users partial-init) 터져 실패 → `api.models` 완전 로드 후
  `command.revision(autogenerate)`/`command.upgrade`로 생성·적용(앱 lifespan과 동일 경로). autogenerate가
  런타임 소유 테이블(checkpoints·mem0_memories·casbin_rule) 삭제·무관 인덱스 churn을 대량으로 끌어와
  (회고 [[hand-authored-migration-ids-collide-silently]] 결) **messages 3컬럼+2인덱스만 남기고 전부 제거**.
- 검증: verify_364(HTTP+DB 통합) C1/C3/C4/C6 전부 PASS + 마이그레이션 실측(단일 head·컬럼 3개·인덱스 2개),
  make test SUITE_OK. C2(HIL/폼 재개 동일 turn_id)는 재개가 pending thread_id를 이어받고 모든 persist
  경로가 그 thread_id를 넘기므로 설계상 성립(산출물형 ask/form은 질문·답이 같은 thread_id).

## OUT (후속)

- **턴 분석 UI/질의**(집계 화면·리포트) — 이 스펙은 **기록**만(분석이 가능해지도록). 분석 표면은 별도 스펙.
- **페르소나→프롬프트 개명**(항목 1) — 분석과 독립, 다음 스펙(365). 이 스펙은 기존 이름(persona) 유지.
- **프롬프트 버전관리**(옵션 c) — 스냅샷으로 충분, 필요 시 후속.
- 과거 이력 소급 turn_id 부여 — 신규 턴부터(과거는 thread_id가 이미 소실).
