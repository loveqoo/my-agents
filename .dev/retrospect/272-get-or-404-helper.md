# 272 — get-or-404 정본화 (스펙 297)

## 무엇을 했나
`obj = await session.get(Model, id)` + `if obj is None: raise HTTPException(404, detail)` 3줄 관용구를
`db.get_or_404(session, model, ident, detail="not found")` 헬퍼로 정본화. PEP 695 제네릭
(`async def get_or_404[T](...) -> T`)로 반환 타입 보존, `@overload` 불필요(항상 raise·None 반환 없음).
**37곳** 변환(blocks 13·providers 5·model_registry 4·rag 2·user_admin 3·eval_* 8·agents 1·chat_context 1).

## 배운 것 / 복리 포인트

- **"전수조사 33"도 렌즈의 함수였다(census-lens 재발)**. 1차 분류 스크립트는 *단일 줄·꼬리주석 없는*
  형태만 매칭 → 33건. 하지만 멀티라인 `session.get(\n …)`·`if (\n X is None\n):`·꼬리 인라인 주석으로
  **형태만 어긋난 동일 순수 패턴 4건**(eval_cases 2·eval_authoring 2)이 남아 있었다. 스펙 OUT에 "near-miss
  보수적 미변환(무해)"으로 적어뒀지만, 그건 딱 사용자가 반복 지적한 "좁은 렌즈의 0". **정규식이 놓친 걸
  '무해'로 방치하지 말고, 조건에 or/and 없을 때만 순수로 판정하는 견고 스캐너(멀티라인·괄호 허용)로 재전수**
  해 37건 전부 편입. → [[probe-deeper-before-concluding]] [[index-layer-for-context-recall]]

- **RBAC 안전 규칙 = session.get은 항상 PK 순수 조회**. 소유권 스코프 fetch는 `select().where()`·
  `scalar_one_or_none`을 쓰지 `.get`을 안 쓴다. 따라서 위험은 오직 **결합 게이트**
  (`if X is None or not may_...`)뿐 — 이건 변환 제외. `session.get(M,id)` + 단독 `if None: 404`는
  스코프 우회 위험이 구조적으로 없다. → [[gate-on-intent-value-not-mutable-baseline]]

- **존재-404 → assert_may_manage 순서가 특권도 방벽**(eval_authoring codex P2 F4). superuser는
  `assert_may_manage(None, superuser)`를 통과해버리므로, 존재 체크가 반드시 **먼저** 와야 한다.
  get_or_404는 None이면 return 전에 raise → assert_may_manage가 None을 못 본다. 변환이 이 순서를
  뒤집지 않는지가 codex 여집합 공격 핵심 축. 순서 보존 확인.

- **dedup이 미사용 import를 드러낸다(패턴 반복)**. eval_cases의 404를 전부 get_or_404로 걷어내자
  `HTTPException` import가 F401. ruff가 잡아 정리 — dedup 후 import 정합은 게이트가 마감.
  → [[sync-wholesale-replace-drops-admin-fields]] 계열(변환이 부수 흔적을 남김).

## 검증 (사다리 3런)
- **단위/게이트**: make metrics-fast(ruff/format/xenon/MI/naming/mypy 0).
- **실인프라 통합**: verify_112(소유권·자가잠금·특권·404-fold)·147(가시성 404-fold)·148(네이밍)·
  104(broker anti-leak) 전부 PASS. verify_103은 **pristine HEAD에서 동일 실패**(StopIteration,
  fake fixture 노후) = 회귀 아님·기존 stale(backlog). 스위트 51/51.
- **적대(codex)**: 여집합 공격 5축(결합 게이트 삼킴·early-return 뒤집기·detail 드리프트·존재/소유 순서
  특권도·별도 게이트 탈락) → **"여집합 공격 실패 — 결함 없음"**. 37건 전수 확인(near-miss 4건 포함),
  detail 문자열 6종 전부 보존, 존재-404→assert_may_manage 순서 유지, 소유권/가시성 게이트 불변.

## 남은 것
- authz `_own_scope`/`_is_admin` dedup(라우터 독립성 설계 결정 + 적대 필요) — backlog.
- eval_* 내부 중복(미조사) — backlog.
- stale verifier(100/103/130/131/190/084) 노후 fixture 수리 — backlog.
