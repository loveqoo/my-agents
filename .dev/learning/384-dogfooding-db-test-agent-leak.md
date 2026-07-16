# 384 — 공유 라이브 DB의 테스트-누수 정리: dev 스윕은 prod 스윕과 다르다

## 맥락

"사용하지 않는 에이전트 있지 않나?"(구남님) 조사 → 도그푸딩 DB 42개 중 **37개가 테스트 누수**
(e2e-agent-* 20·_verify* 2·v/ui 버전테스트 5·mock-a2a/sdk 10). 시드 데모는 5개뿐. e2e/verify가
공유 라이브 DB에 에이전트를 만들고 크래시·불완전 cleanup으로 다 안 지운 것. 정식 API 삭제 관문으로
37개 정리(의존 세션 10·메시지 20·버전 28 cascade), 재발 방지로 `tests/clean_test_agents.py` +
`make clean-test-agents[-apply]` 유틸 신설.

## 교훈

- **공유 라이브 DB에 행을 만드는 테스트는 새 는다 — 정리 주체를 아무도 안 두면.** agents 테이블은
  resource_policy상 "bounded(관리자 페이스)"인데 **테스트가 그 전제를 깬다**. 개별 테스트에 cleanup을
  붙여도 크래시·중단이 남긴다. resource-audit 교훈의 재현: "누수를 개별로 고치지 말고 회수 주체를 둬라."
- **dev-DB 스윕 ≠ prod 스윕.** 이름 패턴(`^e2e-agent-`·`^mock-`)으로 지우는 스윕은 **prod엔 위험**
  (사용자가 그 이름을 쓸 수 있다) → 앱 배치 잡이 아니라 **dev 도구**로 둔다. 도그푸딩 DB 오염은
  prod엔 없는 문제라 앱에 회수 로직을 넣는 건 과설계(YAGNI). 경계 = "이 오염이 prod에도 나나?"
- **파괴 스윕은 KEEP-리스트로 가드하고 정식 관문으로 실행.** 시드 데모 5개를 이름으로 **명시 보존**
  (지울 것을 고르지 말고 남길 것을 고정 — 새 테스트 패턴이 생겨도 시드는 안전). 삭제는 직접 DB DELETE가
  아니라 **API DELETE 라우트**로 — agent_versions cascade·블록 이력(delete_block_history)·세션 정합을
  라우트가 처리(관문 우회 시 고아 행). 기본 **dry-run**, `--apply`로만 실삭제(sweep-debris 패턴 미러).
- **관찰 먼저·애매하면 확인.** 생성처를 코드에서 못 찾은 mock-*(수기 도그푸딩 가능성)는 자동 삭제 않고
  사용자에게 확인(observe-before-remedy·"내가 안 만든 건 함부로 안 지운다"). dry-run으로 KEEP/DEL/의존
  행을 먼저 보인 뒤 실행.

[shared-live-db-leaks-without-reaper, dev-sweep-not-prod-sweep, keep-list-guards-destructive-sweep,
delete-via-route-not-raw, dry-run-and-confirm-ambiguous]
