# 384 — http verify 17건 triage: 앱 결함 0, 순수 드리프트 1 수정·전제/오염 16 격리

> 상태: 초안(AI 작성 → 인간 검토). 성격: 회귀망 위생(테스트 부채 가시화).
> 참고: [[regression-net-quarantine-not-fix-all]] · [[test-all-pollution-masks-regressions]] ·
> [[probe-deeper-before-concluding]] · [[baseline-diff-separates-regression]] · 백로그 "verify 스위트 격리"

## 배경 — test-all이 17건 "새 회귀"를 보고

스펙 383 후 `make test-all`이 http 층 17건을 "격리 목록에 없는 새 회귀"로 보고. 회고 383 교훈대로
**한 번의 test-all은 권위가 아니다**(상태 오염). 결정적으로 판정:

1. **내 변경과 무관**: 17건 전부 batch 무관(383은 batch_routes.py만). grep 전수.
2. **사전존재**: 가장 의심스러운 3건(101 브로커 HIL·102 조율·072 rag)을 baseline(2fbd224, 세션 시작
   *이전*) 서버로 대조 → **동일하게 실패**. 내 리팩터 세션(381/382/383)이 낸 게 아니다.
3. **앱 결함 0**: 17건 단독 실행해 진짜 원인 추출 → **전부 테스트 쪽**(라이브 DB 상태 얽힘·스키마
   진화에 뒤처진 기대치·fragile 테스트 코드). "잠재 실버그" 후보였던 verify_093(모델삭제 FK)도 코드
   읽으니 앱 가드가 이미 컬렉션 참조를 409로 덮음(model_registry.py:347) — 테스트 _cleanup이 route를
   우회한 raw 삭제였다.

## 조치 — 순수 드리프트는 고치고, 전제/오염은 격리

**① 순수 드리프트 수정(DB 무관·고치면 그린)**:
- `verify_047_integration`: `AgentVersion(status="archived")` — status 필드가 스펙 367/369서 제거
  (버전 상태=Agent.active_version 포인터·ever_opened). status 인자 제거 → **ALL PASS**.

**② 전제/오염/하네스 격리(run_suite KNOWN_DRIFT, 정직한 사유)**: 16건. 근본 원인 = **공유 라이브 DB
   격리 부재**(159 raw verify가 한 DB에 얽힘, 백로그 대형 항목). 개별 전제 추격은 두더지잡기라 사유
   달아 격리(부채 가시화, 격리 하네스 생기면 여기서 지운다).
   - RAG 4(036·037·072·103): 기대 컬렉션 미발견 + default 없는 `next()` → StopIteration.
   - 브로커 2(101·102): delete→interrupt 라이브 미발동 — **인프로세스 verify_233은 통과**(코드 정상).
   - MCP 2(054×2)·세션 3(034·055·098)·기억 1(084)·인제스트 1(048): 공유 DB 상태·shape/버킷 드리프트.
   - verify_063: 테스트가 route 우회 agent 직접 insert → created_by NOT NULL(스펙343).
   - verify_093: 테스트 _cleanup의 raw 모델 삭제 → 잔여 컬렉션 FK(앱 가드는 409 정상).
   - verify_057: asyncio Task가 다른 이벤트루프에 attach(테스트 하네스 버그).

## 완료 조건

- verify_047 단독 **ALL PASS**(순수 드리프트 봉합).
- `make test-all` → **SUITE_OK**(17건이 전부 fixed(1) 또는 quarantined(16), "새 회귀" 0).
- `make test`(씨앗 그물) 무영향 = SUITE_OK 유지.

## 아웃(이번 스펙 밖) — 근본 해결

- **공유 라이브 DB 격리 하네스**(fresh-DB-per-run) = 백로그 대형 항목. 격리한 16건은 하네스가 생겨야
  안정적으로 그린 복귀(개별 전제 수정은 재오염). 이번은 **부채 가시화 + 앱 무결성 확증**까지.
- 034의 배지 스코핑 델타 단언·084의 mem0 백엔드 의존 hit shape는 하네스 위에서 재검토.
