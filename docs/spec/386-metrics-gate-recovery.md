# 386 — make metrics 게이트 복구: format 17·naming 17·complexity D2·MI B1

> 상태: 초안(AI 작성 → 인간 검토). 성격: 품질 게이트 위생(스펙 291의 판정자 복원).
> 참고: [[ruler-before-repair-scoreboard]] · 스펙 291(metrics)·292(naming) · 백로그 374 Tier 3(경계)

## 배경 — 게이트가 RED면 게이트가 안 지켜진다

스펙 383·384 검증 중 `make metrics-fast`가 4축 RED로 확인(전부 사전존재 — 383/384와 무관).
게이트가 죽어 있으면 이후 모든 작업의 완료 판정이 부분 게이트로 때워진다(383도 그랬다).

측정(정정 포함):
1. **format 17파일**: ~~ruff 0.15.21 도구 드리프트~~ → **오진**. ruff@0.14.14도 동일 17개 지적 —
   346~372 캠페인 파일들이 `make format` 없이 커밋된 것. 수정=포맷 적용(기계적·동작 불변).
2. **naming R3 10건**: 한 글자 루프 변수(node_templates 6·pipeline 2·eval_harness 1·events 1).
3. **naming R1 7건**: bool 반환 함수명 — 동작형(부수효과+성공 bool: `_acquire_reindex_lock`·
   `_try_become_leader`·`record_block_version`·`reload_schedules` 후보)은 ACTION_WHITELIST 등재
   (부수효과 실증+사유), 순수 술어형(`_eq`·`_pinned_by_approval`·`_pinned_by_artifact`)은 rename.
4. **complexity D 2곳**: `_load_context` D(21) — 문턱 1 초과 · `consolidate_user_memories` D(23).
   헬퍼 추출로 C(≤20) 복귀. **Tier 3(전면 수술) 아님** — 문턱 넘기는 최소 추출.
5. **MI chat.py B(18.77)**: A 문턱(20)까지 1.23 — 소규모 추출로 상승, 부족 시 함수 모듈 추출.

## 경계(스코프 가드)

- chat.py→ChatTurnService·jobs plan/execute 분해 같은 **Tier 3 전면 수술은 이번 범위 밖**(백로그 유지).
- 핫패스(chat·chat_context·jobs) 변경은 동작 불변: suite(실모델)+mypy 베이스라인+SUITE_OK로 검증,
  codex 리뷰(핫패스 추출분).

## 완료 조건(측정 가능) — 결과

- C1: `make metrics-fast` 전판 통과 ✅ (lint·format-check·complexity·maintainability·naming·typecheck 전부 그린).
- C2: `make test` SUITE_OK ✅ (verify_039 통합 잡 포함 db 그물 통과).
- C3: `make suite` → **환경 차단**(PREFLIGHT: 실모델 미등록 — dev DB에 mock 3개뿐, 사전존재 환경
  이지 이번 변경과 무관). **대체 증거로 동작 불변 판정**: ①codex 적대 리뷰 "결함 없음 — 동작 불변"
  (이동 6함수 AST 동일성·consolidation 흐름 매핑·순환 0 확인) ②실채팅 1턴 관통(이동한 trace 조립이
  만든 agentVersion·sentMessagesSource·contextMessages·memoryQuery·memorySaved 전부 정상)
  ③asgi 층 virgin-DB 그물. 실모델 재등록 후 suite 1회가 잔여 확인 항목.
- C4: mypy **0 errors** ✅ — 베이스라인 2건(block_versions bare type)까지 소거(목표 초과).

## 결과 요약

format 17파일 적용 · naming 17→0(rename 13곳+ACTION_WHITELIST 4건 등재) · complexity D2→0
(_load_context 21→C11·consolidate_user_memories 23→C이하, 헬퍼 추출) · chat.py MI B(18.77)→
**A(24.70)**(트레이스 가족 6함수+캡 2상수를 chat_trace.py로 이동, 파사드 재수출 유지) ·
mypy 6→0(신규 union 미협소화 2곳도 mypy가 잡아 isinstance 협소화 — 382 교훈 재현).
