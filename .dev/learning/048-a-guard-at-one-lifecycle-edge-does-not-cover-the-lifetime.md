# 048 — 한 수명 경계(생성)에 건 보장은 수명 전체를 못 덮는다 — 다른 서브시스템이 그 사이 깬다

## 상황
어떤 불변식(예: "이 세션 행은 resume가 찾을 수 있어야 한다")을 **생성 시점에** 보장해 놓고
"연속성 확보"라 선언할 때. 같은 데이터의 **수명 후반을 다루는 다른 서브시스템**(배치 정리·GC·만료·아카이브)이
그 행을 지우거나 옮기면 보장은 깨진다. 가드가 *생성 edge*만 막고 *수명 전체*를 안 덮었기 때문.

## 사례(스펙 049)
소스 미영속 전환 후 HIL 승인 연속성을 위해 `_create_approval`이 세션 행을 `turns=0`으로 lazy-create했다
(생성 가드). 그런데 **배치 턴 정리**(`cleanup_sessions`)가 `turns < N AND idle > 1h` 행을 지운다 →
승인이 1h+ 미해결이면(흔함) 그 세션이 삭제 → resume_approval의 `_load_context`가 새 id 발급 → 대화 고아.
Approval 행은 FK 아닌 plain string이라 살아남아 "동작하는 듯" 보였지만 세션 연결이 끊겼다.
**자가 테스트(A5)는 생성 직후만 봐서 GREEN**, 적대 리뷰가 "정리 단계가 그걸 지우면?"을 짚어 적발.

## 교훈
- **보장은 데이터의 *수명 구간*(생성→소멸)에 걸쳐 표현하라.** "생성 시 만든다"로 끝내지 말고
  "이 조건이면 *지우지 않는다*"를 소멸 경로에도 박아라. 049 수정: cleanup에 `~exists(pending approval)` AND.
- **불변식을 건드릴 수 있는 *모든 쓰기 주체*를 나열하라.** 같은 테이블을 쓰는 코드는 요청 핸들러만이 아니다 —
  배치 잡·마이그레이션·관리 CRUD·cascade가 다 후보. 한 곳에 가드 깔고 끝내면 나머지가 깬다.
- **검증 시점을 수명 끝까지 늘려라.** "생성 직후 존재"만 보는 테스트는 GREEN이어도 거짓 안심.
  회귀는 *대조군*과 함께(049 B6: 같은 나이 비-승인 세션은 삭제됨 → 가드가 빼는 게 맞음을 증명).

## 메타패턴 — "서브유닛 방어는 전체를 못 묶는다"의 **WHEN(수명) 축**
같은 메타패턴의 형제들:
- [[041-bounded-knob-must-cap-the-raw-source]] — WHERE(어느 바이트)
- [[044-a-guard-installed-is-not-a-guard-that-covers]] — WHICH(어느 URL/부수효과)
- [[046-per-read-timeout-is-not-a-whole-stream-deadline]] — WHICH-span(어느 구간)
- [[047-idempotency-on-success-counter-misses-partial-runs]] — WHICH-set(완전성)
- **048(이 글)** — WHEN(수명): 가드가 *한 시점*만 덮고 *전 구간*을 안 덮음. 다른 서브시스템이 다른 시점에 깸.

세트로 묶으면: "방어를 *최종 진실 위치*에, *모든 주체*에 대해, *전 구간*에 걸쳐 걸어라. 한 서브유닛·한 시점·
한 경로의 방어는 happy-path만 GREEN으로 만들고 적대자에게 여집합을 남긴다."
참조: [[adversarial-review-before-destructive-ship]], [[045-integration-fixture-coupled-to-seed-loses-the-rung]].
