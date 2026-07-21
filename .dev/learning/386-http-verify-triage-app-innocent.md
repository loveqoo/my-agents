# 386 — http verify 17건을 "해결"하니 앱 결함은 0: 부패한 건 테스트였다

## 맥락

test-all이 http 17건을 "새 회귀"로 보고 → 개발자 "해결해봅시다". 무작정 17개 고치기 전에 triage:
각 단독 실행해 진짜 원인 추출 → **전부 테스트 쪽**(공유 라이브 DB 상태 얽힘·스키마 진화에 뒤처진
기대치·fragile 테스트 코드). 앱 결함 0. 조치=순수 드리프트 1건(verify_047) 수정·나머지 16건 정직한
사유로 격리(run_suite KNOWN_DRIFT). test-all SUITE_OK. 근본 해결=공유 DB 격리 하네스(백로그).

## 교훈

- **"실패 N건"을 고치기 전에 triage로 앱 결함부터 가려라 — 부패한 건 대개 테스트다.** 17건을 단독
  실행해 진짜 원인을 뽑으니 하나도 앱 버그가 아니었다: RAG의 `coroutine raised StopIteration`은
  테스트가 기대 컬렉션 못 찾아 **default 없는 `next()`**가 터진 것, 063은 테스트가 route 우회 직접
  insert, 093은 테스트 _cleanup의 raw 삭제. 실패 메시지의 예외 타입만 보면 "코드 버그"로 오인한다 —
  발생 지점이 테스트 파일인지 앱인지가 갈림.
- **"잠재 실버그" 후보도 코드를 읽으면 이미 막혀 있다([[probe-deeper-before-concluding]]).** verify_093의
  FK 위반을 보고 "모델삭제 가드가 컬렉션 참조를 안 본다"고 가설을 세웠으나, delete_model 핸들러를
  읽으니 **이미 409로 컬렉션 참조를 막고 있었다**(스펙 048 적대리뷰서 봉합). 테스트가 그 라우트를
  우회한 raw 삭제였을 뿐. 고치기 전에 가드의 실재를 확인하라 — 이번에도 가설이 틀렸다.
- **순수 드리프트(DB 무관)와 상태/전제 의존을 갈라라 — 전자만 고치고 후자는 격리([[regression-net-quarantine-not-fix-all]]).**
  verify_047의 `status="archived"`는 스펙 367/369서 제거된 필드라 깨끗한 DB서도 TypeError → 인자
  제거로 ALL PASS(그물 복귀). 반면 034의 "inject 37, count 정확히 +37" 델타나 098의 잔여 세션 혼입은
  **공유 DB선 원리적으로 못 통과** → 격리. 개별 전제 수정은 재오염되는 두더지잡기, 근본은 격리 하네스.
- **격리 규모 자체가 신호다 — 17건 중 16건 격리 = 격리 하네스 부재의 청구서.** 한둘이면 개별 수정이
  맞지만, 16건이 같은 원인(공유 라이브 DB)이면 개별 추격이 아니라 **자(하네스)를 만들 때**라는 뜻.
  격리는 그 부채를 숫자로 가시화한다(SUITE_OK인데 KNOWN_DRIFT가 두꺼움 = "그물은 초록이나 http는 빚").
- **회귀 판정은 baseline 대조가 결정적([[baseline-diff-separates-regression]]).** http 테스트는 라이브
  서버(:8000)를 쳐서 baseline 코드로 재검하려면 **워크트리로 이전 커밋 서버를 띄워** 대조해야 한다.
  3건(101/102/072)이 2fbd224(세션 시작 전)서 동일 실패 → 사전존재 확정, 내 세션 무죄. `--reload`
  스테일 가설은 깨끗한 재기동 후에도 동일 실패로 기각(환경 아닌 사전존재 데이터).

[triage-before-fix-app-usually-innocent, guard-often-already-exists-read-first,
pure-drift-fix-state-dependent-quarantine, quarantine-size-signals-harness-need, baseline-via-worktree-server]
