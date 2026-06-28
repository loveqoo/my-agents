# 045 — 통합 픽스처가 데모 시드에 결합하면, 카탈로그를 비울 때 통합 rung이 함께 증발한다

## 맥락

스펙 046에서 코드/인프라 빌딩블록(github·kubernetes MCP, repo.merge·k8s.write 권한,
Code Reviewer·Ops Copilot 에이전트)을 카탈로그에서 제거. 그런데 041의 통합 프로브
`probe_041_chat_integration.py`는 **github MCP + Code Reviewer 에이전트가 시드돼 있다는 전제**로
chat.py의 실 글루(에이전트→interrupt 게이트)를 증명하고 있었다. 046이 그 빌딩블록을 *설계상*
지우자, 통합 시나리오가 더는 시드되지 않아 프로브가 무용해졌다(게다가 agent_pk 조회가
`scalar_one()`이라 에이전트 부재 시 크래시까지).

## 교훈

**통합 테스트가 데모/시드 데이터를 픽스처로 빌려 쓰면, 그 시드가 정리되는 순간 테스트도 함께
죽는다.** learning 040은 "실인프라 통합 rung이 단위·적대가 못 보는 글루 결함을 잡는다"고 했다 —
*rung을 얻는 법*. 045는 그 반대편이다: **그 rung을 어떻게 잃지 않는가.** 데모 시드는 카탈로그
정리·리브랜딩·디프리케이션의 1순위 삭제 대상이라, 거기에 결합한 통합 픽스처는 수명이 데모
데이터에 묶인다.

## 어떻게 적용

- **통합 테스트는 자기 픽스처를 소유하라(self-fixture).** 시드 데모 데이터에 piggyback하지 말고,
  테스트가 setup에서 필요한 에이전트/MCP/권한을 직접 만들고 teardown에서 지워라. 그러면 카탈로그를
  비워도 통합 rung이 살아남는다.
- **시드 데이터를 지울 땐 "그 데이터를 전제하는 테스트"를 grep하라.** 카탈로그에서 재료를 빼는
  작업의 적대 리뷰 체크리스트에 "이 재료를 픽스처로 쓰는 테스트·프로브·브라우저 샷이 있나?"를
  넣어라(046에선 shot-agents-037도 삭제된 Code Reviewer를 클릭하고 있었다 — 같은 결합의 다른 면).
- **rung을 의도적으로 포기한다면, 메커니즘은 다른 rung으로 보존하고 빚으로 기록하라.** 046은
  통합 시나리오를 시드에서 지웠지만 게이트 *메커니즘*은 runtime 정책으로, *단위 시맨틱*은
  verify_041(green)로 보존하고, 프로브는 크래시 대신 graceful SKIP으로 바꾼 뒤 spec §7에
  "미래에 admin 승인이 필요한 웹 액션이 추가되면 self-fixture로 rung 재구성"이라 명시했다.
  포기는 괜찮다 — *조용한* 포기(크래시·green 위장)가 문제다.

## 관련

- [[040-real-infra-integration-catches-glue-and-deployment-drift]] (rung을 얻는 법 ↔ 045는 잃지 않는 법)
- [[042-a-move-breaks-references-in-both-directions]] (시드 재료를 쓰는 *테스트 자산*도 들어오는 참조)
- [[038-adversarial-review-finds-what-invariants-miss]] (B1·B2를 잡은 게 적대 리뷰)
- [[025-seed-mock-drift-needs-migration-and-shared-constant]] (시드↔라이브 drift)
