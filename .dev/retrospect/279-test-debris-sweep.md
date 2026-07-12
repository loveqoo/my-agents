# 279 — 테스트 잔해 스윕 + 기존 정리(스펙 304)

## 무엇을 했나
스펙 303이 갈라낸 두 번째 층(테스트 잔해)을 처리. dev DB 58 에이전트 중 53이 브라우저/verify 테스트
산물(teardown 부재로 누적)이었고, **프리픽스 화이트리스트 + seed keeplist 이중 가드** 스윕 스크립트
(`tests/sweep_debris.py`, dry-run 기본·--apply)를 만들어 지금 정리(58→5)하고 make 타깃으로 재사용화.

## 배운 것 / 복리 포인트

- **"인프라 없음" 결론 전에 계층을 갈라라(303 교훈의 즉시 재적용)**. 이 작업 시작 시 postgres가 또
  안 떠 있었는데, 303에서 배운 대로 바로 OrbStack VM·컨테이너를 갈라 봤다 — `my-agents-postgres-1`이
  Exited라 `docker start`로 살렸다. 한 번 배운 계층 분리를 다음 작업 Context에서 상기·적용한 게
  복리(회고는 다음 작업에서 상기될 때만 값이 붙는다). → [[probe-deeper-before-concluding]]

- **잔해 정리의 스코프는 "재발원"까지 봐야 진짜 마감**. 53개를 지우기만 하면 다음 테스트 실행에 또
  쌓인다. 조사로 재발원(브라우저 `_fixture.mjs`가 임시 *유저*만 지우고 그 유저가 만든 *에이전트*는
  방치, `suite`만 멱등)을 짚고, 사용자와 방지책(스윕+make 타깃)까지 정한 뒤 착수. **삭제는 증상,
  teardown 부재가 병**. → [[installed-guard-isnt-covering-guard]] 계열(가드가 있어도 덮는 범위가 어긋남).

- **프리픽스 화이트리스트 vs keeplist는 "미래 실 데이터 보호"로 갈린다**. 오늘 기준 비-seed 53은 전부
  테스트 프리픽스라 "seed 5 빼고 전삭제"와 결과가 같다. 하지만 앞으로 UI로 만들 실 에이전트도
  agent_id가 랜덤 hex라 seed와 구분 안 됨 → **전삭제식은 미래 실 데이터를 지운다**. 이름 프리픽스만이
  테스트/실사용을 가르는 유일 신호라, 사용자가 화이트리스트를 택함(미래 보호). 이중 가드로 seed도 겸
  보호(belt-and-suspenders). → [[gate-on-intent-value-not-mutable-baseline]]

- **비가역 삭제 스크립트는 dry-run 기본 + 명시 --apply + 적대 리뷰**. 파괴 경로라 (1) dry-run이 기본이고
  실삭제는 `--apply` 뒤로(사고 방지), (2) codex 적대 리뷰를 **삭제 실행 전에** 받음. codex가
  "여집합 공격 실패(결함 없음)" 판정하면서도 **운영 위험 하나**를 덤으로 짚음 — `approval-demo`만
  하이픈 없는 프리픽스라 `approval-demographic…` 같은 실명을 오매칭할 수 있음. 그 자리서 exact-name
  매칭으로 조임(프리픽스는 전부 하이픈으로 끝나 실명 오매칭 방지). **적대 리뷰가 인접 위험을 덤으로
  잡는다**. → [[adversarial-review-before-destructive-ship]] [[use-codex-for-adversarial-verification]]

- **cascade는 "DB단 ondelete"에 위임하고 실측으로 마감**. Agent 자식 FK가 DB단 CASCADE라
  `DELETE FROM agents WHERE id=ANY(:pks)` 한 문장이 versions·sessions·messages·feedback를 함께 정리.
  approvals는 SET NULL(감사행 보존). ORM 관계 로드(1247세션·5772메시지) 없이 효율적. 삭제 후
  카운트 실측으로 확증(agents 58→5·versions 70→17·sessions 1380→133·messages 6048→276·시드데이터
  collections/personas/providers/eval_* 전부 불변). 자가선언 금지, 측정 마감.

## 검증 (사다리 3런)
- **dry-run 시맨틱**: 화이트리스트가 53 전량 잡고 seed 5는 0 매칭, DB 카운트 불변(58→58)으로 무삭제 확인.
- **실인프라(--apply)**: 실 dev DB 적용 후 agents=5(seed만)·잔여 잔해 0·시드데이터 불가침 실측.
- **적대(codex, read-only)**: "화이트리스트 여집합·seed 오삭제·cascade 과삭제"를 refute → "여집합 공격
  실패", FK ondelete을 models.py와 대조 확증, `approval-demo` 오매칭 운영 위험만 지적(즉시 조임).

## 남은 것 / 주의
- 스윕은 **make 타깃 재사용**(브라우저 배치 후 `make sweep-debris-apply`) — 러너 부재라 자동 exit-hook은
  배제(전-DB 스윕이 매 스크립트 exit마다 과중). 새 테스트가 미등록 프리픽스를 쓰면 화이트리스트 갱신 필요.
- 근본 방지(일회용 DB per run·테스트별 finally DELETE)는 OUT(사용자 스윕 선택). 재발이 잦으면 후속.
- mem0_memories·personas 자체 테스트 잔재는 에이전트 FK 없어 별개(미처리).
