# 282 — 테스트 격리 마감(스펙 307)

## 무엇을 했나
backlog가 "stale verifier"로 묶은 6건을 **서버 띄우고 전수 진단** → 실제론 3부류였다: (1) 100·101·103은
stale이 아니라 **인프라**(dev 서버·mock MCP·mock 임베딩 필요)였을 뿐, (2) 036·061은 **드리프트**(네이밍·
구조), (3) 056은 **상태 의존**(공유 dev DB). 036(밑줄→대시)·061(seam 개명+시그니처 추종)을 고치고,
056은 **일회용 DB 격리 러너**(`tests/_throwaway_db.py`)로 virgin DB에서 돌게 해 마감.

## 배운 것 / 복리 포인트

- **"stale"라 묶인 것도 전수 진단하면 부류가 갈린다 — 특히 "인프라 미기동"을 드리프트로 오분류**. 100·
  101·103은 dev 서버(mock MCP·mock 임베딩)를 안 띄우고 돌려서 red였을 뿐, 서버 띄우니 exit=0. 스펙 306
  중엔 pristine 대조로 "기존 실패"까지만 확인하고 stale로 뭉갰는데, **서버를 띄우고 재측정하니 코드 무결**
  이었다. "red = 코드 문제"가 아니라 "red = 실행 전제 미충족"일 수 있다 — stale 판정 전에 **실행 환경부터
  갖추고 재측정**. → [[verification-ladder-three-rungs]] [[probe-deeper-before-concluding]]

- **몽키패치 seam은 "실호출 이름"을 따라간다 — 개명·시그니처까지**(302 교훈의 심화). 061은 옛
  `_load_exposed_ui_agent`를 패치했으나 코드는 `_load_exposed_agent`로 개명·`_agent_a2a_skills` 신설·
  `exposed_agent_a2a`가 `request`+`_principal` 파라미터를 얻었다. seam 패치는 **현재 실호출 이름**으로
  재지정하고, 계약이 바뀐 함수는 **인자까지 추종**해야 한다(재수출 심볼·구명칭·옛 시그니처는 조용히
  실효). → [[monkeypatch-seam-contract]]

- **전역 집계를 검사하는 테스트는 소유-픽스처만으론 부족 — virgin DB가 필요**. 056은 이미 고유 prefix로
  자기 세션을 심고 자가정리했지만, `cleanup_sessions` dry-run의 **sample이 전역 캡(20)**이라 dev DB의
  ambient 133 세션이 sample을 채우면 자기 픽스처가 안 보여 결정성이 깨진다(그리고 "not in sample"
  단언들이 *부재로 우연히 통과*=거짓 초록). prefix 스코핑은 자기 것을 *심고 지우는* 데는 되지만
  **전역 관측을 통제하진 못한다** → 전역 연산 테스트는 일회용 DB로 격리. → [[cap-the-raw-source-not-the-buffer]]

- **격리 러너는 in-process 재바인딩보다 subprocess+DATABASE_URL이 깨끗**. 앱이 `from .db import
  SessionLocal`을 import 시점 바인딩해 in-process로 엔진을 갈면 이미 import된 모듈이 옛 바인딩을 잡는다.
  대신 **자식 subprocess가 격리 DATABASE_URL로 fresh import**하게 하면(smoke_303 계보) 재바인딩 마법
  없이 완전 격리. 대상 스크립트는 무수정, `_THROWAWAY_DB` 가드로 자동 재실행. 전 149 verifier 전수
  이관은 이 러너 채택의 점진 후속(SessionLocal DI 리팩터 불요). → [[structure-first-boundary-is-spec]]

- **DB 생성/삭제 러너는 URL을 문자열로 자르면 안 된다 — 라이브로 샌다(codex)**. `rpartition('/')`로 db명을
  바꾸면 쿼리스트링(`?sslrootcert=/tmp/x`)이 있을 때 마지막 '/'가 db path가 아니라 query 내부라 db명
  교체가 어긋나 **CREATE EXTENSION·자식 실행이 라이브 `agents`를 친다**. SQLAlchemy `make_url().set(
  database=…)`로 컴포넌트만 정확히 교체해야 안전. 또 `_create`를 try 밖에 두면 부분 생성(CREATE 성공+
  extension 실패)이 finally를 못 타 tmp가 샌다 → try 안으로. **비가역 인프라 러너는 happy-path(우리 .env엔
  쿼리 없음)로 초록이어도 적대자가 형식 변주로 라이브 유출을 짚는다.** → [[adversarial-review-before-destructive-ship]] [[cap-the-raw-source-not-the-buffer]]

## 검증 (사다리)
- **각 verifier green**: 036·061(서버↑, exit=0)·056(자동 격리, exit=0)·100·101·103(서버↑, 무변경 PASS).
- **격리 무오염**: 056 실행 후 라이브 dev DB 무접촉(일회용 DB에서만 심고 drop), URL 견고성 단위 확인
  (쿼리스트링 있어도 database만 교체).
- **적대(codex, read-only)**: 러너 drop/가드를 refute → High2(URL 파싱 라이브 유출)+Medium1(부분생성
  누수) 적발 → SQLAlchemy make_url + `_create` try 이동으로 봉합. `_drop`/`pg_terminate_backend`는 tmp
  바인딩이라 여집합 실패.

## 남은 것 / 주의
- **전 149 verifier의 일회용-DB 전면 이관**은 OUT — 앱의 `SessionLocal` import-시점 바인딩 때문에 전면
  격리는 러너 채택(점진) 또는 SessionLocal DI가 선행(별건). 이번은 러너 씨앗 + 3건 마감.
- 100·101·103은 **dev 서버 up이 실행 전제**(stale 아님) — verify 배치 게이트를 만들면 서버 기동을 전제에 명시.
- verify_*.py는 게이트 밖 ad-hoc(실게이트=make suite). 기존 F401/E702(056 등)는 tests/ 미게이트 잔여(무관).
- dev api 서버는 진단 위해 기동해 둠(정상 dev 상태).
